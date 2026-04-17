from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

import git

from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.agents.execution_facts import (
    build_execution_facts,
    build_historical_execution_facts,
    format_execution_facts_section,
    format_historical_execution_facts_section,
    is_redundant_completed_step,
    latest_replan_failure_message,
    merge_execution_facts,
    should_mark_setup_complete,
)
from backend.app.agents.planner_context import (
    build_context_budget_section,
    build_critical_previews_section,
    build_dialog_context,
    build_execution_history,
    build_key_files_section,
    build_react_trace_context,
    build_retrieved_context_section,
    parse_json_payload,
    sanitize_decision_payload,
)
from backend.app.agents.task_trace import (
    build_observation_trace_entry,
    build_planned_step_payloads,
    build_react_trace_entries,
    build_step_failure_message,
)
from backend.app.agents.types import (
    AgentGraphState,
    ExecutionStepModel,
    IntentAnalysis,
    PlannerDecisionModel,
    ToolResult,
)
from backend.app.core.config import get_settings
from backend.app.executors.local import LocalExecutor
from backend.app.models.enums import ApprovalMode, ApprovalStatus, MessageType, StepStatus, TaskStatus
from backend.app.rag.indexer import RepositoryIndexer
from backend.app.schemas import TaskEvent
from backend.app.services.app_settings import get_or_create_app_settings
from backend.app.services.dialogs import add_message, get_dialog
from backend.app.services.event_bus import publish_event
from backend.app.services.github_service import GitHubContext, GitHubService
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
        self.settings = get_settings()
        self.indexer = RepositoryIndexer()
        self.executor = LocalExecutor()
        self.github_service = GitHubService()
        self.llm = (
            ChatOpenAI(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_model,
                temperature=0.1,
            )
            if self.settings.has_usable_openai_api_key
            else None
        )

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
        base_context = self.indexer.build_planner_context(
            self.db,
            owner=owner,
            name=name,
            branch=branch,
            query=user_message,
        )
        key_files = list(base_context.get("key_files", []))
        extensions = set(base_context.get("extensions", []))
        filenames = {Path(source).name for source in key_files}
        lower_filenames = {name.lower() for name in filenames}
        is_node = "package.json" in lower_filenames
        is_python = "requirements.txt" in lower_filenames or ".py" in extensions
        install_command = "npm install" if is_node else "pip install -r requirements.txt"
        test_command = "npm test" if is_node else "pytest"
        return {
            "repository_summary": base_context.get("repository_summary", ""),
            "install_command": install_command,
            "test_command": test_command,
            "stack": "node" if is_node else "python" if is_python else "generic",
            "key_files": sorted(key_files)[:40],
            "extensions": sorted(extensions)[:20],
            "retrieved_context": base_context.get("retrieved_context", []),
            "critical_file_previews": base_context.get("critical_file_previews", []),
            "total_files": base_context.get("total_files", 0),
            "total_chunks": base_context.get("total_chunks", 0),
        }

    def _plan_next_actions(self, state: AgentGraphState, task) -> PlannerDecisionModel:
        decision = self._plan_next_actions_with_llm(state, task)
        if decision is None:
            decision = self._plan_next_actions_with_rules(state, task)
        return self._normalize_decision(decision, state, task)

    def _plan_next_actions_with_llm(self, state: AgentGraphState, task) -> PlannerDecisionModel | None:
        """Thought phase of the ReAct loop.

        The LLM receives the full Thought/Action/Observation trace built up so
        far, reasons about it (the Thought), and returns exactly ONE next action
        to execute.  Its reasoning field IS the Thought that will be appended to
        the trace before the next Observation is captured.
        """
        if self.llm is None:
            return None

        context_preview = "\n".join(state["dialog_context"][-8:]) if state["dialog_context"] else "No prior dialog context."
        react_trace = build_react_trace_context(task)
        execution_history = build_execution_history(task)
        execution_facts = format_execution_facts_section(task)
        historical_execution_facts = format_historical_execution_facts_section(state["historical_execution_facts"])
        latest_failure_note = latest_replan_failure_message(task)
        context_budget = build_context_budget_section(
            dialog_context=state["dialog_context"],
            repository_context=state["repository_context"],
            task=task,
        )
        repository_summary = state["repository_context"].get("repository_summary", "")
        key_files_section = build_key_files_section(state["repository_context"])
        retrieved_section = build_retrieved_context_section(state["repository_context"])
        preview_section = build_critical_previews_section(state["repository_context"])
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a ReAct (Reason + Act) autonomous DevOps agent. "
                    "You operate in a strict Thought → Action → Observation loop. "
                    "Each call to you is one Thought: you read all prior Observations, "
                    "reason about what they mean for the goal, and decide exactly ONE next Action. "
                    "The system will execute that action, capture the Observation, and call you again. "
                    "Return strict JSON only with keys: intent, reasoning, is_complete, completion_summary, steps. "
                    "intent keys: objective, category, complexity, needs_repository_context. "
                    "Each step keys: title, kind, command, image, parameters, requires_approval, success_criteria. "
                    "Allowed step kinds: shell, docker, github. "
                    "Rules: "
                    "1) Plan EXACTLY 1 executable step per response — this is the ReAct single-action constraint. "
                    "2) If the task is complete, set is_complete=true and return steps=[]. "
                    "3) Do not emit pseudo-steps like plan, analyze, summarize, or explain as executable steps. "
                    "4) Every step must be directly executable by the backend without extra natural language interpretation. "
                    "5) Set requires_approval=true for every emitted step. "
                    "6) Prefer inspection commands first when repository state is uncertain. "
                    "7) Prefer these shell command prefixes when possible: ls, pwd, echo, cat, rg, sed, head, tail, git, python, python3, pip, pip3, pytest, npm, node, yarn, pnpm, bash, sh. "
                    "8) Commands outside that preferred set are still allowed but require explicit human approval. "
                    "9) Use the provided repository evidence and make sure the planned step is consistent with those facts. "
                    "10) reasoning is your visible Thought for the UI: read the latest Observation in the ReAct trace, "
                    "    reflect on what succeeded or failed, then explain in one or two sentences exactly what you will do next and why. "
                    "11) Never repeat actions that already appear as completed Observations in the ReAct trace. "
                    "    If all setup steps succeeded, move to the next unmet objective or mark the task complete. "
                    "12) If latest_replan_failure_message is provided, treat it as the operator-selected failure context "
                    "    that should drive the next recovery action.",
                ),
                (
                    "human",
                    "User request:\n{user_message}\n\n"
                    "ContextBudget:\n{context_budget}\n\n"
                    "ReAct trace (Thought / Action / Observation history):\n{react_trace}\n\n"
                    "Recent dialog context:\n{dialog_context}\n\n"
                    "RepositorySummary:\n{repository_summary}\n\n"
                    "KeyFiles:\n{key_files}\n\n"
                    "RetrievedContext:\n{retrieved_context}\n\n"
                    "CriticalFilePreviews:\n{critical_file_previews}\n\n"
                    "Execution facts:\n{execution_facts}\n\n"
                    "Historical execution facts from previous tasks in this dialog:\n{historical_execution_facts}\n\n"
                    "Latest replan failure message:\n{latest_replan_failure_message}\n\n"
                    "Execution history:\n{execution_history}",
                ),
            ]
        )

        try:
            response = self.llm.invoke(
                prompt.format_messages(
                    user_message=task.user_message,
                    context_budget=context_budget,
                    react_trace=react_trace,
                    dialog_context=context_preview,
                    repository_summary=repository_summary,
                    key_files=key_files_section,
                    retrieved_context=retrieved_section,
                    critical_file_previews=preview_section,
                    execution_facts=execution_facts,
                    historical_execution_facts=historical_execution_facts,
                    latest_replan_failure_message=latest_failure_note,
                    execution_history=execution_history,
                )
            )
            payload = parse_json_payload(str(response.content))
            payload = sanitize_decision_payload(payload, user_message=task.user_message)
            return PlannerDecisionModel.model_validate(payload)
        except Exception as exc:
            logger.warning("LLM planner failed, fallback to rule planner: %s", exc)
            return None

    def _plan_next_actions_with_rules(self, state: AgentGraphState, task) -> PlannerDecisionModel:
        user_message = task.user_message
        repository_context = state["repository_context"]
        lowered = user_message.lower()
        intent = IntentAnalysis(
            objective=user_message,
            category="automation",
            complexity="medium",
            needs_repository_context=True,
        )
        executed_titles = {step.title for step in task.steps}
        steps: list[ExecutionStepModel] = []

        issue_match = re.search(r"(?:issue|pr|pull request)\s*#?(\d+)", lowered)
        workflow_match = re.search(r"workflow\s+([a-zA-Z0-9_.-]+)", user_message)

        if issue_match and "comment" in lowered and not executed_titles:
            steps.append(
                ExecutionStepModel(
                    title=f"Post comment on issue #{issue_match.group(1)}",
                    kind="github",
                    parameters={
                        "action": "create_issue_comment",
                        "issue_number": int(issue_match.group(1)),
                        "body": f"Automated message from AI DevOps Copilot:\n\n{user_message}",
                    },
                    success_criteria="A GitHub issue comment is created successfully.",
                )
            )
            intent.category = "github_comment"
        elif "workflow" in lowered and ("trigger" in lowered or "dispatch" in lowered) and not executed_titles:
            steps.append(
                ExecutionStepModel(
                    title="Trigger GitHub Actions workflow",
                    kind="github",
                    parameters={
                        "action": "dispatch_workflow",
                        "workflow_id": workflow_match.group(1) if workflow_match else "ci.yml",
                    },
                    success_criteria="The workflow dispatch API accepts the workflow run.",
                )
            )
            intent.category = "github_actions"
        else:
            install_command = repository_context["install_command"]
            test_command = repository_context["test_command"]

            if any(token in lowered for token in ["install", "setup", "environment", "dependencies"]) and "Install dependencies" not in executed_titles:
                steps.append(
                    ExecutionStepModel(
                        title="Install dependencies",
                        kind="shell",
                        command=install_command,
                        success_criteria="Dependencies install without command failure.",
                    )
                )

            if any(token in lowered for token in ["test", "pytest", "unit test", "run tests"]) and "Run tests and capture failure points" not in executed_titles:
                steps.append(
                    ExecutionStepModel(
                        title="Run tests and capture failure points",
                        kind="shell",
                        command=test_command,
                        success_criteria="The test command runs and returns actionable output.",
                    )
                )

            if ("docker" in lowered or "container" in lowered) and "Run containerized validation command" not in executed_titles:
                steps.append(
                    ExecutionStepModel(
                        title="Run containerized validation command",
                        kind="docker",
                        image="python:3.10-slim"
                        if repository_context["stack"] == "python"
                        else "node:20-alpine",
                        command=test_command,
                        success_criteria="The command executes successfully inside the container.",
                    )
                )

            if not steps and "Inspect repository workspace" not in executed_titles:
                steps.append(
                    ExecutionStepModel(
                        title="Inspect repository workspace",
                        kind="shell",
                        command="ls -la",
                        success_criteria="Workspace contents are listed for further planning.",
                    )
                )

        return PlannerDecisionModel(
            intent=intent,
            reasoning="Rule-based fallback planner generated the next executable steps.",
            is_complete=bool(task.steps) and not steps,
            completion_summary="Rule planner determined there are no more safe executable steps."
            if bool(task.steps) and not steps
            else None,
            steps=steps,
        )

    def _normalize_decision(self, decision: PlannerDecisionModel, state: AgentGraphState, task) -> PlannerDecisionModel:
        execution_facts = build_execution_facts(task)
        historical_execution_facts = state["historical_execution_facts"]
        merged_execution_facts = merge_execution_facts(execution_facts, historical_execution_facts)
        completed_signatures = set(merged_execution_facts["completed_signatures"])
        safe_steps: list[ExecutionStepModel] = []
        for raw_step in decision.steps:
            try:
                step = ExecutionStepModel.model_validate(raw_step)
            except ValidationError:
                continue

            if is_redundant_completed_step(step, completed_signatures):
                continue
            step.requires_approval = True
            safe_steps.append(step)

        if len(safe_steps) > 1:
            logger.warning(
                "Planner returned %s steps for task %s; keeping only the first step to enforce the single-action ReAct loop.",
                len(safe_steps),
                task.id,
            )
            safe_steps = safe_steps[:1]

        if not safe_steps and not decision.is_complete:
            if should_mark_setup_complete(task, merged_execution_facts):
                return PlannerDecisionModel(
                    intent=decision.intent,
                    reasoning=decision.reasoning,
                    is_complete=True,
                    completion_summary=(
                        decision.completion_summary
                        or "Environment setup steps already completed successfully; no further setup action is needed."
                    ),
                    steps=[],
                )
            safe_steps = [
                ExecutionStepModel(
                    title="Inspect repository workspace",
                    kind="shell",
                    command="ls -la",
                    success_criteria="Workspace contents are listed for further planning.",
                )
            ]

        return PlannerDecisionModel(
            intent=decision.intent,
            reasoning=decision.reasoning,
            is_complete=decision.is_complete and not safe_steps,
            completion_summary=decision.completion_summary,
            steps=safe_steps,
        )

    def _execute_step(
        self,
        *,
        plan_step: ExecutionStepModel,
        owner: str,
        name: str,
        branch: str,
        on_output=None,
    ) -> ToolResult:
        if plan_step.kind == "shell":
            result = self.executor.execute(
                request=self.executor_request(
                    plan_step.command or "",
                    owner,
                    name,
                    branch,
                    on_output=on_output,
                )
            )
            return ToolResult(
                step=plan_step.title,
                success=result.success,
                output=result.stdout or result.stderr,
                error=result.stderr if not result.success else None,
                metadata=result.metadata,
            )

        if plan_step.kind == "docker":
            result = self.executor.run_docker(
                image=plan_step.image or "python:3.10-slim",
                command=plan_step.command,
                working_directory=self._ensure_workspace(owner, name, branch),
                on_output=on_output,
            )
            return ToolResult(
                step=plan_step.title,
                success=result.success,
                output=result.stdout or result.stderr,
                error=result.stderr if not result.success else None,
                metadata=result.metadata,
            )

        if plan_step.kind == "github":
            context = GitHubContext(owner=owner, name=name, branch=branch)
            action = plan_step.parameters.get("action")
            if action is None:
                action = self._infer_github_action(plan_step)
            if action == "create_issue_comment":
                body = plan_step.parameters.get("body") or plan_step.parameters.get("comment_body") or plan_step.command
                response = self.github_service.create_issue_comment(
                    context,
                    issue_number=plan_step.parameters["issue_number"],
                    body=body,
                )
            elif action == "dispatch_workflow":
                response = self.github_service.dispatch_workflow(
                    context,
                    workflow_id=plan_step.parameters["workflow_id"],
                    ref=branch,
                )
            elif action == "create_pull_request":
                response = self.github_service.create_pull_request(
                    context,
                    title=plan_step.parameters["title"],
                    body=plan_step.parameters["body"],
                    head=plan_step.parameters["head"],
                    base=plan_step.parameters.get("base", branch),
                )
            else:
                raise ValueError(f"Unsupported GitHub action: {action}")

            return ToolResult(
                step=plan_step.title,
                success=True,
                output=json.dumps(response, indent=2),
                metadata=response,
            )

        raise ValueError(f"Unsupported step kind: {plan_step.kind}")

    def executor_request(
        self,
        command: str,
        owner: str,
        repository_name: str,
        branch: str,
        *,
        on_output=None,
    ):
        working_directory = self._ensure_workspace(owner, repository_name, branch)
        return self.executor_request_class(
            command,
            working_directory,
            allow_unlisted_command=True,
            on_output=on_output,
        )

    @property
    def executor_request_class(self):
        from backend.app.executors.base import ExecutionRequest

        return ExecutionRequest

    def _build_summary(
        self,
        user_message: str,
        results: list[dict[str, Any]],
        completion_summary: str | None = None,
    ) -> str:
        if self.llm is None:
            lines = [f"Request: {user_message}", "", "Workflow results:"]
            for result in results:
                prefix = "OK" if result["success"] else "FAILED"
                lines.append(f"- [{prefix}] {result['step']}: {result['output'][:240]}")
            if completion_summary:
                lines.extend(["", f"Completion signal: {completion_summary}"])
            return "\n".join(lines)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You summarize DevOps automation runs for humans. Be concise and technical.",
                ),
                (
                    "human",
                    "User request: {user_message}\n\nCompletion signal: {completion_summary}\n\nExecution results:\n{results}",
                ),
            ]
        )
        response = self.llm.invoke(
            prompt.format_messages(
                user_message=user_message,
                completion_summary=completion_summary or "No explicit completion signal provided.",
                results=json.dumps(results, indent=2),
            )
        )
        return str(response.content)

    def _ensure_workspace(self, owner: str, name: str, branch: str) -> str:
        workspace_path = self.settings.repo_cache_dir / f"{owner}__{name}"
        clone_url = f"https://github.com/{owner}/{name}.git"
        if self.settings.github_token:
            clone_url = f"https://{self.settings.github_token}:x-oauth-basic@github.com/{owner}/{name}.git"

        if not workspace_path.exists():
            try:
                git.Repo.clone_from(clone_url, workspace_path.as_posix(), branch=branch, depth=1)
            except git.exc.GitCommandError:
                git.Repo.clone_from(clone_url, workspace_path.as_posix(), depth=1)
            return workspace_path.as_posix()

        try:
            repository = git.Repo(workspace_path)
            repository.git.fetch("origin", branch, depth=1)
            repository.git.checkout(branch)
            repository.git.pull("origin", branch)
        except Exception as exc:
            logger.warning("Failed to refresh repository workspace: %s", exc)
        return workspace_path.as_posix()

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
        try:
            return re.split(r"\s+", command.strip(), maxsplit=1)[0] or None
        except Exception:
            return None

    def _infer_github_action(self, step: ExecutionStepModel) -> str | None:
        parameters = step.parameters or {}
        if "issue_number" in parameters and (
            "body" in parameters or "comment_body" in parameters or step.command
        ):
            return "create_issue_comment"
        if "workflow_id" in parameters:
            return "dispatch_workflow"
        if {"title", "body", "head"}.issubset(parameters.keys()):
            return "create_pull_request"
        return None

    def _requires_approval(self, step: ExecutionStepModel) -> bool:
        approval_mode = get_or_create_app_settings(self.db).approval_mode
        if approval_mode == ApprovalMode.ALL_ALLOW:
            return False
        if approval_mode == ApprovalMode.NO:
            return True
        if step.kind == "github":
            return True
        if step.kind == "shell":
            first_token = self._command_first_token(step.command or "")
            return bool(first_token and first_token not in self.settings.command_allowlist)
        if step.kind == "docker":
            first_token = self._command_first_token(step.command or "")
            return bool(first_token and first_token not in self.settings.command_allowlist)
        return True
