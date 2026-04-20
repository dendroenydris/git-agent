from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from backend.app.agents.execution_facts import build_historical_execution_facts
from backend.app.agents.planner_context import build_dialog_context
from backend.app.agents.runtime import AgentRuntime
from backend.app.agents.task_trace import (
    build_observation_trace_entry,
    build_planned_step_payloads,
    build_react_trace_entries,
    build_step_failure_message,
)
from backend.app.agents.types import AgentGraphState, ExecutionStepModel, PlannerDecisionModel, ToolResult
from backend.app.models.enums import ApprovalStatus, MessageType, StepStatus, TaskStatus
from backend.app.schemas import TaskEvent
from backend.app.services.dialogs import add_message, get_dialog
from backend.app.services.event_bus import publish_event
from backend.app.services.tasks import (
    append_plan_steps,
    get_task,
    merge_plan_state,
    set_task_status,
    task_to_read,
    update_step,
)


logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.runtime = AgentRuntime(db)
        self.settings = self.runtime.settings

    def process_task(self, task_id: str) -> dict[str, Any]:
        task = get_task(self.db, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        dialog = get_dialog(self.db, task.dialog_id)
        if dialog is None or dialog.repository is None:
            raise ValueError("Dialog repository context is missing")

        state: AgentGraphState = {
            "task_id": task.id,
            "user_message": task.user_message,
            "owner": dialog.repository.owner,
            "name": dialog.repository.name,
            "branch": dialog.repository.branch,
            "dialog_context": build_dialog_context(dialog.messages),
            "historical_execution_facts": build_historical_execution_facts(dialog, current_task_id=task.id),
            "repository_context": task.plan_json.get("repository_context", {}) if task.plan_json else {},
            "plan": task.plan_json or {},
            "results": (task.result_json or {}).get("results", []),
            "summary": task.summary or "",
            "waiting_for_human": False,
            "is_complete": False,
            "iteration_count": len((task.plan_json or {}).get("planner_iterations", [])),
            "completion_summary": "",
        }
        return self._run_agent_loop(state)

    def _run_agent_loop(self, state: AgentGraphState) -> AgentGraphState:
        """Main ReAct loop: Thought → Action → Observation → Thought → …

        Each iteration of the while-loop is one complete T-A-O cycle:
          1. THOUGHT  – the LLM reasons about the goal and the latest observation,
                        then plans exactly ONE next action.
          2. ACTION   – that single action is executed by _execute_next_step.
          3. OBSERVATION – the result is captured and appended to the ReAct trace,
                        which the LLM will read on the next Thought.
        """
        task = get_task(self.db, state["task_id"])
        if task is None:
            raise ValueError(f"Task {state['task_id']} not found")

        set_task_status(self.db, task, status=TaskStatus.RUNNING)
        if not state["repository_context"]:
            state["repository_context"] = self._build_repository_context(
                owner=state["owner"],
                name=state["name"],
                branch=state["branch"],
                user_message=task.user_message,
            )
            merge_plan_state(
                self.db,
                task,
                repository_context=state["repository_context"],
            )
            self.db.commit()
            refreshed = get_task(self.db, task.id)
            if refreshed:
                self._emit_task_event(refreshed, "task_updated")

        # Each iteration is one T-A-O cycle; 20 cycles ≈ up to 20 individual actions.
        max_iterations = 20
        while state["iteration_count"] < max_iterations:
            task = get_task(self.db, state["task_id"])
            if task is None:
                raise ValueError(f"Task {state['task_id']} not found")

            # ── ACTION + OBSERVATION ──────────────────────────────────────────
            # If a planned action is waiting, execute exactly ONE step and
            # capture its observation before returning to the Thought phase.
            if self._has_pending_steps(task):
                state = self._execute_next_step(state, task)
                if state["waiting_for_human"]:
                    return state
                task = get_task(self.db, state["task_id"])
                if task is None:
                    raise ValueError(f"Task {state['task_id']} not found")
                if state["is_complete"] and not self._has_pending_steps(task):
                    break
                # After every observation, fall through to the Thought phase
                # so the LLM can reason about the result before the next action.

            if state["is_complete"]:
                break

            # ── THOUGHT ──────────────────────────────────────────────────────
            # The LLM reads the full T-A-O trace and produces its next Thought
            # together with exactly one Action to execute.
            decision = self._plan_next_actions(state, task)
            next_iteration = state["iteration_count"] + 1
            state["iteration_count"] = next_iteration
            state["completion_summary"] = decision.completion_summary or state["completion_summary"]
            state["is_complete"] = decision.is_complete
            state["dialog_context"].append(f"agent_thought: {decision.reasoning[:300]}")

            planned_step_payloads = build_planned_step_payloads(decision.steps, iteration=next_iteration)
            react_trace_entries = build_react_trace_entries(
                reasoning=decision.reasoning,
                steps_payload=planned_step_payloads,
                iteration=next_iteration,
            )

            planner_iteration = {
                "iteration": state["iteration_count"],
                "reasoning": decision.reasoning,
                "is_complete": decision.is_complete,
                "completion_summary": decision.completion_summary,
                "steps": planned_step_payloads,
            }
            merge_plan_state(
                self.db,
                task,
                intent=decision.intent.model_dump(),
                repository_context=state["repository_context"],
                planner_iteration=planner_iteration,
                react_trace_entries=react_trace_entries,
            )
            if decision.steps:
                append_plan_steps(self.db, task, planned_step_payloads)

            state["plan"] = task.plan_json or {}
            self.db.commit()
            refreshed = get_task(self.db, task.id)
            if refreshed:
                self._emit_task_event(refreshed, "task_updated")

            if not decision.steps and decision.is_complete:
                break

            if not decision.steps and not decision.is_complete:
                raise ValueError("Planner returned no executable steps and did not mark the task complete")

        if not state["is_complete"] and state["iteration_count"] >= max_iterations:
            raise ValueError("Planner exceeded maximum iterations before completing the task")

        return self._summarize_task(state)

    def _execute_pending_steps(self, state: AgentGraphState, task) -> AgentGraphState:
        pending_steps = sorted(
            (
                step
                for step in task.steps
                if step.status in {StepStatus.PENDING, StepStatus.RUNNING, StepStatus.WAITING_FOR_HUMAN}
            ),
            key=lambda item: item.position,
        )
        for db_step in pending_steps:
            plan_step = self._step_from_db(db_step)

            if self._requires_approval(plan_step) and task.approval_status != ApprovalStatus.APPROVED:
                approval_message = "Waiting for operator approval before execution."
                if plan_step.kind == "shell" and plan_step.command:
                    first_token = self._command_first_token(plan_step.command)
                    if first_token and first_token not in self.settings.command_allowlist:
                        approval_message = (
                            "Waiting for operator approval before execution. "
                            f"Command prefix '{first_token}' is outside the normal allowlist and will run only after approval."
                        )
                update_step(
                    self.db,
                    task,
                    position=db_step.position,
                    status=StepStatus.WAITING_FOR_HUMAN,
                    output=approval_message,
                )
                merge_plan_state(
                    self.db,
                    task,
                    react_trace_entries=[
                        build_observation_trace_entry(
                            db_step=db_step,
                            status="waiting_for_human",
                            content=approval_message,
                        )
                    ],
                )
                state["dialog_context"].append(f"agent_observation: {approval_message[:300]}")
                set_task_status(
                    self.db,
                    task,
                    status=TaskStatus.WAITING_FOR_HUMAN,
                    approval_status=ApprovalStatus.PENDING,
                    summary=f"Approval required for step {db_step.position}: {plan_step.title}",
                    result={"results": state["results"]},
                )
                self.db.commit()
                refreshed = get_task(self.db, task.id)
                if refreshed:
                    self._emit_task_event(
                        refreshed,
                        "approval_required",
                        {"step": db_step.position, "title": plan_step.title},
                    )
                state["waiting_for_human"] = True
                return state

            update_step(self.db, task, position=db_step.position, status=StepStatus.RUNNING)
            set_task_status(
                self.db,
                task,
                status=TaskStatus.RUNNING,
                approval_status=ApprovalStatus.APPROVED
                if task.approval_status == ApprovalStatus.APPROVED
                else ApprovalStatus.NOT_REQUIRED,
                result={"results": state["results"]},
            )
            self.db.commit()
            refreshed = get_task(self.db, task.id)
            if refreshed:
                self._emit_task_event(refreshed, "task_updated")

            try:
                result = self._execute_step(
                    plan_step=plan_step,
                    owner=state["owner"],
                    name=state["name"],
                    branch=state["branch"],
                    task_id=task.id,
                    on_output=self._build_step_output_callback(task, db_step),
                )
            except Exception as exc:
                logger.exception("Step execution raised an exception: %s", exc)
                result = ToolResult(
                    step=plan_step.title,
                    success=False,
                    output="",
                    error=str(exc),
                    metadata={"exception_type": type(exc).__name__},
                )
            state["results"].append(result.model_dump())

            if result.success:
                update_step(
                    self.db,
                    task,
                    position=db_step.position,
                    status=StepStatus.COMPLETED,
                    output=result.output,
                    metadata=result.metadata,
                )
                merge_plan_state(
                    self.db,
                    task,
                    react_trace_entries=[
                        build_observation_trace_entry(
                            db_step=db_step,
                            status="completed",
                            content=result.output,
                            error=result.error,
                        )
                    ],
                )
                state["dialog_context"].append(f"agent_observation: {(result.output or '')[:300]}")
                if self._requires_approval(plan_step):
                    set_task_status(
                        self.db,
                        task,
                        status=TaskStatus.RUNNING,
                        approval_status=ApprovalStatus.NOT_REQUIRED,
                        result={"results": state["results"]},
                    )
            else:
                update_step(
                    self.db,
                    task,
                    position=db_step.position,
                    status=StepStatus.FAILED,
                    output=result.output,
                    error=result.error,
                    metadata=result.metadata,
                )
                merge_plan_state(
                    self.db,
                    task,
                    react_trace_entries=[
                        build_observation_trace_entry(
                            db_step=db_step,
                            status="failed",
                            content=result.output,
                            error=result.error,
                        )
                    ],
                )
                set_task_status(
                    self.db,
                    task,
                    status=TaskStatus.RUNNING,
                    approval_status=ApprovalStatus.NOT_REQUIRED,
                    summary=f"Step {db_step.position} failed: {plan_step.title}. Replanning next actions.",
                    error=result.error or "Execution failed",
                    result={"results": state["results"]},
                )
                failure_message = build_step_failure_message(
                    position=db_step.position,
                    title=plan_step.title,
                    command=plan_step.command,
                    output=result.output,
                    error=result.error,
                )
                agent_message = add_message(
                    self.db,
                    dialog_id=task.dialog_id,
                    content=failure_message,
                    message_type=MessageType.AGENT,
                    task_id=task.id,
                    summary="Step failed, replanning",
                    metadata={
                        "step": db_step.position,
                        "title": plan_step.title,
                        "kind": plan_step.kind,
                        "command": plan_step.command,
                        "error": result.error,
                    },
                )
                state["dialog_context"].append(f"agent_observation: {failure_message[:300]}")
                self.db.commit()
                refreshed = get_task(self.db, task.id)
                if refreshed:
                    self._emit_task_event(refreshed, "task_updated")
                self._emit_message_event(task.dialog_id, agent_message.id, failure_message)
                return state

            self.db.commit()
            refreshed = get_task(self.db, task.id)
            if refreshed:
                self._emit_task_event(refreshed, "task_updated")

        state["waiting_for_human"] = False
        return state

    def _execute_next_step(self, state: AgentGraphState, task) -> AgentGraphState:
        """Execute exactly ONE pending step (Action phase of a single ReAct cycle).

        Unlike _execute_pending_steps, this method processes only the first
        pending step and returns immediately so the orchestrator loop can feed
        the observation back to the LLM for the next Thought.
        """
        pending_steps = sorted(
            (
                step
                for step in task.steps
                if step.status in {StepStatus.PENDING, StepStatus.RUNNING, StepStatus.WAITING_FOR_HUMAN}
            ),
            key=lambda item: item.position,
        )
        if not pending_steps:
            state["waiting_for_human"] = False
            return state

        db_step = pending_steps[0]
        plan_step = self._step_from_db(db_step)

        if self._requires_approval(plan_step) and task.approval_status != ApprovalStatus.APPROVED:
            approval_message = "Waiting for operator approval before execution."
            if plan_step.kind == "shell" and plan_step.command:
                first_token = self._command_first_token(plan_step.command)
                if first_token and first_token not in self.settings.command_allowlist:
                    approval_message = (
                        "Waiting for operator approval before execution. "
                        f"Command prefix '{first_token}' is outside the normal allowlist and will run only after approval."
                    )
            update_step(
                self.db,
                task,
                position=db_step.position,
                status=StepStatus.WAITING_FOR_HUMAN,
                output=approval_message,
            )
            merge_plan_state(
                self.db,
                task,
                react_trace_entries=[
                    build_observation_trace_entry(
                        db_step=db_step,
                        status="waiting_for_human",
                        content=approval_message,
                    )
                ],
            )
            state["dialog_context"].append(f"agent_observation: {approval_message[:300]}")
            set_task_status(
                self.db,
                task,
                status=TaskStatus.WAITING_FOR_HUMAN,
                approval_status=ApprovalStatus.PENDING,
                summary=f"Approval required for step {db_step.position}: {plan_step.title}",
                result={"results": state["results"]},
            )
            self.db.commit()
            refreshed = get_task(self.db, task.id)
            if refreshed:
                self._emit_task_event(
                    refreshed,
                    "approval_required",
                    {"step": db_step.position, "title": plan_step.title},
                )
            state["waiting_for_human"] = True
            return state

        update_step(self.db, task, position=db_step.position, status=StepStatus.RUNNING)
        set_task_status(
            self.db,
            task,
            status=TaskStatus.RUNNING,
            approval_status=ApprovalStatus.APPROVED
            if task.approval_status == ApprovalStatus.APPROVED
            else ApprovalStatus.NOT_REQUIRED,
            result={"results": state["results"]},
        )
        self.db.commit()
        refreshed = get_task(self.db, task.id)
        if refreshed:
            self._emit_task_event(refreshed, "task_updated")

        try:
            result = self._execute_step(
                plan_step=plan_step,
                owner=state["owner"],
                name=state["name"],
                branch=state["branch"],
                task_id=task.id,
                on_output=self._build_step_output_callback(task, db_step),
            )
        except Exception as exc:
            logger.exception("Step execution raised an exception: %s", exc)
            result = ToolResult(
                step=plan_step.title,
                success=False,
                output="",
                error=str(exc),
                metadata={"exception_type": type(exc).__name__},
            )
        state["results"].append(result.model_dump())

        if result.success:
            update_step(
                self.db,
                task,
                position=db_step.position,
                status=StepStatus.COMPLETED,
                output=result.output,
                metadata=result.metadata,
            )
            merge_plan_state(
                self.db,
                task,
                react_trace_entries=[
                    build_observation_trace_entry(
                        db_step=db_step,
                        status="completed",
                        content=result.output,
                        error=result.error,
                    )
                ],
            )
            state["dialog_context"].append(f"agent_observation: {(result.output or '')[:300]}")
            if self._requires_approval(plan_step):
                set_task_status(
                    self.db,
                    task,
                    status=TaskStatus.RUNNING,
                    approval_status=ApprovalStatus.NOT_REQUIRED,
                    result={"results": state["results"]},
                )
        else:
            update_step(
                self.db,
                task,
                position=db_step.position,
                status=StepStatus.FAILED,
                output=result.output,
                error=result.error,
                metadata=result.metadata,
            )
            merge_plan_state(
                self.db,
                task,
                react_trace_entries=[
                    build_observation_trace_entry(
                        db_step=db_step,
                        status="failed",
                        content=result.output,
                        error=result.error,
                    )
                ],
            )
            set_task_status(
                self.db,
                task,
                status=TaskStatus.RUNNING,
                approval_status=ApprovalStatus.NOT_REQUIRED,
                summary=f"Step {db_step.position} failed: {plan_step.title}. Replanning next actions.",
                error=result.error or "Execution failed",
                result={"results": state["results"]},
            )
            failure_message = build_step_failure_message(
                position=db_step.position,
                title=plan_step.title,
                command=plan_step.command,
                output=result.output,
                error=result.error,
            )
            agent_message = add_message(
                self.db,
                dialog_id=task.dialog_id,
                content=failure_message,
                message_type=MessageType.AGENT,
                task_id=task.id,
                summary="Step failed, replanning",
                metadata={
                    "step": db_step.position,
                    "title": plan_step.title,
                    "kind": plan_step.kind,
                    "command": plan_step.command,
                    "error": result.error,
                },
            )
            state["dialog_context"].append(f"agent_observation: {failure_message[:300]}")
            self.db.commit()
            refreshed = get_task(self.db, task.id)
            if refreshed:
                self._emit_task_event(refreshed, "task_updated")
            self._emit_message_event(task.dialog_id, agent_message.id, failure_message)
            state["waiting_for_human"] = False
            return state

        self.db.commit()
        refreshed = get_task(self.db, task.id)
        if refreshed:
            self._emit_task_event(refreshed, "task_updated")

        state["waiting_for_human"] = False
        return state

    def _summarize_task(self, state: AgentGraphState) -> AgentGraphState:
        task = get_task(self.db, state["task_id"])
        if task is None:
            raise ValueError(f"Task {state['task_id']} not found")

        summary = self._build_summary(task.user_message, state["results"], state["completion_summary"])
        state["summary"] = summary

        set_task_status(
            self.db,
            task,
            status=TaskStatus.COMPLETED,
            summary=summary,
            result={"results": state["results"]},
        )
        agent_message = add_message(
            self.db,
            dialog_id=task.dialog_id,
            content=summary,
            message_type=MessageType.AGENT,
            task_id=task.id,
            summary="Workflow completed",
            metadata={"results": state["results"]},
        )
        self.db.commit()

        refreshed = get_task(self.db, task.id)
        if refreshed:
            self._emit_task_event(refreshed, "task_updated")
        self._emit_message_event(task.dialog_id, agent_message.id, summary)
        return state

    def _build_repository_context(
        self,
        *,
        owner: str,
        name: str,
        branch: str,
        user_message: str,
    ) -> dict[str, Any]:
        return self.runtime.build_repository_context(
            owner=owner,
            name=name,
            branch=branch,
            user_message=user_message,
        )

    def _plan_next_actions(self, state: AgentGraphState, task) -> PlannerDecisionModel:
        return self.runtime.plan_next_actions(
            task=task,
            user_message=task.user_message,
            dialog_context=state["dialog_context"],
            repository_context=state["repository_context"],
            historical_execution_facts=state["historical_execution_facts"],
        )

    def _plan_next_actions_with_llm(self, state: AgentGraphState, task) -> PlannerDecisionModel | None:
        return self.runtime.plan_next_actions_with_llm(
            task=task,
            user_message=task.user_message,
            dialog_context=state["dialog_context"],
            repository_context=state["repository_context"],
            historical_execution_facts=state["historical_execution_facts"],
        )

    def _plan_next_actions_with_rules(self, state: AgentGraphState, task) -> PlannerDecisionModel:
        return self.runtime.plan_next_actions_with_rules(
            task=task,
            user_message=task.user_message,
            repository_context=state["repository_context"],
        )

    def _normalize_decision(self, decision: PlannerDecisionModel, state: AgentGraphState, task) -> PlannerDecisionModel:
        return self.runtime.normalize_decision(
            decision=decision,
            task=task,
            historical_execution_facts=state["historical_execution_facts"],
        )

    def _execute_step(
        self,
        *,
        plan_step: ExecutionStepModel,
        owner: str,
        name: str,
        branch: str,
        task_id: str | None = None,
        on_output=None,
    ) -> ToolResult:
        return self.runtime.execute_step(
            plan_step=plan_step,
            owner=owner,
            name=name,
            branch=branch,
            task_id=task_id,
            on_output=on_output,
        )

    def executor_request(
        self,
        command: str,
        owner: str,
        repository_name: str,
        branch: str,
        *,
        task_id: str | None = None,
        on_output=None,
    ):
        return self.runtime.executor_request(
            command=command,
            owner=owner,
            repository_name=repository_name,
            branch=branch,
            task_id=task_id,
            on_output=on_output,
        )

    @property
    def executor_request_class(self):
        return self.runtime.executor_request_class

    def _build_summary(
        self,
        user_message: str,
        results: list[dict[str, Any]],
        completion_summary: str | None = None,
    ) -> str:
        return self.runtime.build_summary(
            user_message=user_message,
            results=results,
            completion_summary=completion_summary,
        )

    def _ensure_workspace(self, owner: str, name: str, branch: str, *, task_id: str | None = None) -> str:
        return self.runtime.ensure_workspace(owner, name, branch, task_id=task_id)

    def _emit_task_event(self, task, event_type: str, payload: dict[str, Any] | None = None) -> None:
        publish_event(
            TaskEvent(
                type=event_type,
                dialog_id=task.dialog_id,
                task_id=task.id,
                payload={
                    "task": task_to_read(task).model_dump(mode="json"),
                    **(payload or {}),
                },
            )
        )

    def _emit_message_event(self, dialog_id: str, message_id: str, content: str) -> None:
        publish_event(
            TaskEvent(
                type="message_added",
                dialog_id=dialog_id,
                message_id=message_id,
                payload={
                    "message": {
                        "id": message_id,
                        "content": content,
                    }
                },
            )
        )

    def _emit_step_output_event(self, task, db_step, *, stream: str, chunk: str) -> None:
        publish_event(
            TaskEvent(
                type="step_output",
                dialog_id=task.dialog_id,
                task_id=task.id,
                payload={
                    "step_id": db_step.id,
                    "step_position": db_step.position,
                    "stream": stream,
                    "chunk": chunk,
                },
            )
        )

    def _build_step_output_callback(self, task, db_step):
        def _callback(stream: str, chunk: str) -> None:
            self._emit_step_output_event(task, db_step, stream=stream, chunk=chunk)

        return _callback

    def _has_pending_steps(self, task) -> bool:
        return any(step.status in {StepStatus.PENDING, StepStatus.RUNNING, StepStatus.WAITING_FOR_HUMAN} for step in task.steps)

    def _step_from_db(self, db_step) -> ExecutionStepModel:
        payload = dict(db_step.metadata_json or {})
        payload.setdefault("title", db_step.title)
        payload.setdefault("kind", db_step.kind)
        payload.setdefault("command", db_step.command)
        payload.setdefault("requires_approval", db_step.requires_approval)
        return ExecutionStepModel.model_validate(payload)

    def _command_first_token(self, command: str) -> str | None:
        return self.runtime.command_first_token(command)

    def _infer_github_action(self, step: ExecutionStepModel) -> str | None:
        return self.runtime.infer_github_action(step)

    def _requires_approval(self, step: ExecutionStepModel) -> bool:
        return self.runtime.requires_approval(step)
