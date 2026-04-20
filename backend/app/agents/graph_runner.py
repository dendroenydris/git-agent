from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from backend.app.agents.execution_facts import build_historical_execution_facts
from backend.app.agents.graph_state import GraphAgentState
from backend.app.agents.planner_context import build_dialog_context
from backend.app.agents.runtime import AgentRuntime
from backend.app.agents.task_trace import (
    build_observation_trace_entry,
    build_planned_step_payloads,
    build_react_trace_entries,
)
from backend.app.agents.tools import GraphToolbox
from backend.app.agents.types import ExecutionStepModel
from backend.app.models.enums import ApprovalStatus, StepStatus, TaskStatus
from backend.app.services.activity import publish_task_snapshot
from backend.app.services.dialogs import get_dialog
from backend.app.services.tasks import (
    append_plan_steps,
    get_task,
    get_task_graph,
    initialize_task_graph,
    merge_plan_state,
    set_task_graph_active_node,
    set_task_status,
    update_step,
    update_task_graph_metadata,
    update_task_graph_node,
)


logger = logging.getLogger(__name__)


class LangGraphRunner:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.runtime = AgentRuntime(db)
        self.worktree_manager = self.runtime.worktree_manager

    def process_task(self, task_id: str) -> dict[str, Any]:
        task = get_task(self.db, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        dialog = get_dialog(self.db, task.dialog_id)
        if dialog is None or dialog.repository is None:
            raise ValueError("Dialog repository context is missing")

        state = self._build_initial_state(task=task, dialog=dialog)
        graph = self._build_graph()
        final_state = graph.invoke(state)
        self.db.commit()
        return final_state

    def _build_graph(self):
        workflow = StateGraph(GraphAgentState)
        workflow.add_node("planner_agent", self._planner_agent_node)
        workflow.add_node("execution_agent", self._execution_agent_node)
        workflow.add_node("review_agent", self._review_agent_node)
        workflow.set_entry_point("planner_agent")
        workflow.add_conditional_edges(
            "planner_agent",
            self._route_after_planner,
            {
                "execution_agent": "execution_agent",
                "review_agent": "review_agent",
                END: END,
            },
        )
        workflow.add_conditional_edges(
            "execution_agent",
            self._route_after_execution,
            {
                "review_agent": "review_agent",
                END: END,
            },
        )
        workflow.add_conditional_edges(
            "review_agent",
            self._route_after_review,
            {
                "planner_agent": "planner_agent",
                END: END,
            },
        )
        return workflow.compile()

    def _build_initial_state(self, *, task, dialog) -> GraphAgentState:
        task_graph = get_task_graph(task)
        return {
            "task_id": task.id,
            "dialog_id": dialog.id,
            "owner": dialog.repository.owner,
            "name": dialog.repository.name,
            "branch": dialog.repository.branch,
            "user_message": task.user_message,
            "repository_context": dict((task.plan_json or {}).get("repository_context") or {}),
            "dialog_context": build_dialog_context(dialog.messages),
            "historical_execution_facts": build_historical_execution_facts(dialog, current_task_id=task.id),
            "task_graph": task_graph,
            "results": list((task.result_json or {}).get("results", [])),
            "completion_summary": task.summary or "",
            "awaiting_approval": task.status == TaskStatus.WAITING_FOR_HUMAN,
            "current_node_id": task_graph.get("active_node_id"),
            "error": task.error,
        }

    def _planner_agent_node(self, state: GraphAgentState) -> GraphAgentState:
        task = get_task(self.db, state["task_id"])
        if task is None:
            raise ValueError(f"Task {state['task_id']} not found")

        task_graph = get_task_graph(task)
        if task_graph.get("status") in {"completed", "failed"}:
            return self._sync_state(task, state)
        if self._next_execution_node(task_graph) is not None or self._next_review_node(task_graph) is not None:
            return self._sync_state(task, state)

        iteration = self._planner_iteration_count(task_graph) + 1
        if iteration > 20:
            raise ValueError("Graph planner exceeded maximum iterations before completing the task")

        workspace = self.worktree_manager.ensure_task_worktree(
            owner=state["owner"],
            name=state["name"],
            branch=state["branch"],
            task_id=state["task_id"],
        )

        if not state["repository_context"]:
            state["repository_context"] = self.runtime.build_repository_context(
                owner=state["owner"],
                name=state["name"],
                branch=state["branch"],
                user_message=state["user_message"],
            )

        state["repository_context"]["worktree_path"] = workspace["worktree_path"]
        state["repository_context"]["base_repo_path"] = workspace["base_repo_path"]

        decision = self.runtime.plan_next_actions(
            task=task,
            user_message=state["user_message"],
            dialog_context=state["dialog_context"],
            repository_context=state["repository_context"],
            historical_execution_facts=state["historical_execution_facts"],
        )

        planned_step_payloads = build_planned_step_payloads(decision.steps, iteration=iteration)
        react_trace_entries = build_react_trace_entries(
            reasoning=decision.reasoning,
            steps_payload=planned_step_payloads,
            iteration=iteration,
        )
        merge_plan_state(
            self.db,
            task,
            intent=decision.intent.model_dump(),
            repository_context=state["repository_context"],
            planner_iteration={
                "iteration": iteration,
                "reasoning": decision.reasoning,
                "is_complete": decision.is_complete,
                "completion_summary": decision.completion_summary,
                "steps": planned_step_payloads,
            },
            react_trace_entries=react_trace_entries,
        )

        existing_steps_count = len(task.steps)
        if planned_step_payloads:
            append_plan_steps(self.db, task, planned_step_payloads)
        new_db_steps = task.steps[existing_steps_count:]

        planner_node_id = f"planner-{task.id}-{iteration}"
        execution_node_id = f"execute-{task.id}-{iteration}"
        review_node_id = f"review-{task.id}-{iteration}"
        nodes = list(task_graph.get("nodes", []))
        edges = list(task_graph.get("edges", []))

        nodes.append(
            {
                "id": planner_node_id,
                "agent": "PlannerAgent",
                "title": "Plan graph workflow",
                "status": "completed",
                "depends_on": [],
                "tool_name": None,
                "tool_call": {},
                "result_summary": decision.reasoning,
                "error": None,
                "iteration": iteration,
                "is_complete": decision.is_complete,
                "completion_summary": decision.completion_summary,
            }
        )

        if decision.steps:
            step = decision.steps[0]
            db_step = new_db_steps[0]
            nodes.append(
                {
                    "id": execution_node_id,
                    "agent": "ExecutionAgent",
                    "title": step.title,
                    "status": "pending",
                    "depends_on": [planner_node_id],
                    "tool_name": self._tool_name_for_step(step),
                    "tool_call": self._tool_call_for_step(step),
                    "result_summary": None,
                    "error": None,
                    "iteration": iteration,
                    "step_position": db_step.position,
                    "step_id": db_step.id,
                }
            )
            edges.append({"source": planner_node_id, "target": execution_node_id})

        review_dependencies = [execution_node_id] if decision.steps else [planner_node_id]
        nodes.append(
            {
                "id": review_node_id,
                "agent": "ReviewAgent",
                "title": "Review execution results",
                "status": "pending",
                "depends_on": review_dependencies,
                "tool_name": None,
                "tool_call": {},
                "result_summary": None,
                "error": None,
                "iteration": iteration,
            }
        )
        edges.append({"source": review_dependencies[0], "target": review_node_id})

        initialize_task_graph(
            self.db,
            task,
            nodes=nodes,
            edges=edges,
            active_node_id=execution_node_id if decision.steps else review_node_id,
            worktree_path=workspace["worktree_path"],
            base_repo_path=workspace["base_repo_path"],
            status="running",
        )
        set_task_status(
            self.db,
            task,
            status=TaskStatus.RUNNING,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            result={"results": state["results"]},
        )
        self.db.commit()
        refreshed = get_task(self.db, task.id)
        if refreshed:
            publish_task_snapshot(refreshed)

        state["dialog_context"].append(f"agent_thought: {decision.reasoning[:300]}")
        return self._sync_state(task, state)

    def _execution_agent_node(self, state: GraphAgentState) -> GraphAgentState:
        task = get_task(self.db, state["task_id"])
        if task is None:
            raise ValueError(f"Task {state['task_id']} not found")

        task_graph = get_task_graph(task)
        execution_node = self._next_execution_node(task_graph)
        if execution_node is None:
            return self._sync_state(task, state)

        node_id = execution_node["id"]
        db_step = self._db_step_for_execution_node(task, execution_node)
        if db_step is None:
            raise ValueError(f"Execution node {node_id} is missing its task step")

        set_task_graph_active_node(self.db, task, node_id=node_id)
        update_task_graph_node(self.db, task, node_id=node_id, status="running")
        update_task_graph_metadata(self.db, task, status="running")
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
            publish_task_snapshot(refreshed)

        tool_step = self._step_from_graph_node(execution_node)
        if self.runtime.requires_approval(tool_step) and task.approval_status != ApprovalStatus.APPROVED:
            approval_message = f"Approval required before running graph node: {execution_node['title']}"
            update_task_graph_node(
                self.db,
                task,
                node_id=node_id,
                status="waiting_for_human",
                result_summary=approval_message,
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
            set_task_status(
                self.db,
                task,
                status=TaskStatus.WAITING_FOR_HUMAN,
                approval_status=ApprovalStatus.PENDING,
                summary=approval_message,
                result={"results": state["results"]},
            )
            self.db.commit()
            refreshed = get_task(self.db, task.id)
            if refreshed:
                publish_task_snapshot(refreshed, event_type="approval_required")
            state["dialog_context"].append(f"agent_observation: {approval_message[:300]}")
            state["awaiting_approval"] = True
            return self._sync_state(task, state)

        toolbox = GraphToolbox(
            self.runtime,
            owner=state["owner"],
            name=state["name"],
            branch=state["branch"],
            task_id=state["task_id"],
        )
        tool = toolbox.get_tool(execution_node["tool_name"])
        tool_result = tool.invoke(deepcopy(execution_node["tool_call"]))
        state["results"].append(tool_result)
        succeeded = bool(tool_result.get("success"))

        if succeeded:
            update_step(
                self.db,
                task,
                position=db_step.position,
                status=StepStatus.COMPLETED,
                output=tool_result.get("output"),
                metadata=tool_result.get("metadata"),
            )
            merge_plan_state(
                self.db,
                task,
                react_trace_entries=[
                    build_observation_trace_entry(
                        db_step=db_step,
                        status="completed",
                        content=tool_result.get("output"),
                        error=tool_result.get("error"),
                    )
                ],
            )
            if self.runtime.requires_approval(tool_step):
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
                output=tool_result.get("output"),
                error=tool_result.get("error"),
                metadata=tool_result.get("metadata"),
            )
            merge_plan_state(
                self.db,
                task,
                react_trace_entries=[
                    build_observation_trace_entry(
                        db_step=db_step,
                        status="failed",
                        content=tool_result.get("output"),
                        error=tool_result.get("error"),
                    )
                ],
            )
            set_task_status(
                self.db,
                task,
                status=TaskStatus.RUNNING,
                approval_status=ApprovalStatus.NOT_REQUIRED,
                error=tool_result.get("error"),
                result={"results": state["results"]},
            )

        update_task_graph_node(
            self.db,
            task,
            node_id=node_id,
            status=StepStatus.COMPLETED.value if succeeded else StepStatus.FAILED.value,
            result_summary=str(tool_result.get("output") or tool_result.get("error") or "")[:240]
            or execution_node["title"],
            error=tool_result.get("error"),
        )
        update_task_graph_metadata(self.db, task, status="running")
        if succeeded:
            task.error = None
            self.db.add(task)
        set_task_status(
            self.db,
            task,
            status=TaskStatus.RUNNING,
            approval_status=ApprovalStatus.NOT_REQUIRED
            if succeeded and self.runtime.requires_approval(tool_step)
            else task.approval_status,
            error=tool_result.get("error") if not succeeded else task.error,
            result={"results": state["results"]},
        )
        self.db.commit()
        refreshed = get_task(self.db, task.id)
        if refreshed:
            publish_task_snapshot(refreshed)

        observation_text = str(tool_result.get("error") or tool_result.get("output") or "")[:300]
        if observation_text:
            state["dialog_context"].append(f"agent_observation: {observation_text}")
        state["awaiting_approval"] = False
        return self._sync_state(task, state)

    def _review_agent_node(self, state: GraphAgentState) -> GraphAgentState:
        task = get_task(self.db, state["task_id"])
        if task is None:
            raise ValueError(f"Task {state['task_id']} not found")
        if state["awaiting_approval"]:
            return self._sync_state(task, state)

        task_graph = get_task_graph(task)
        review_node = self._next_review_node(task_graph)
        if review_node is None:
            return self._sync_state(task, state)

        iteration = int(review_node.get("iteration") or 0)
        planner_node = self._planner_node_for_iteration(task_graph, iteration)
        execution_nodes = self._execution_nodes_for_iteration(task_graph, iteration)
        has_failure = any(node.get("status") == StepStatus.FAILED.value for node in execution_nodes)
        planner_marked_complete = bool(planner_node and planner_node.get("is_complete"))

        update_task_graph_node(
            self.db,
            task,
            node_id=review_node["id"],
            status="completed",
            result_summary=(
                planner_node.get("completion_summary")
                if planner_marked_complete and not execution_nodes and planner_node is not None
                else "Review complete. Continue planning."
            ),
        )

        if planner_marked_complete and not execution_nodes:
            completion_summary = self.runtime.build_summary(
                user_message=state["user_message"],
                results=state["results"],
                completion_summary=planner_node.get("completion_summary") or "Graph workflow completed.",
            )
            update_task_graph_metadata(self.db, task, status="completed", active_node_id=None)
            set_task_graph_active_node(self.db, task, node_id=None)
            set_task_status(
                self.db,
                task,
                status=TaskStatus.COMPLETED,
                approval_status=ApprovalStatus.NOT_REQUIRED,
                summary=completion_summary,
                result={"results": state["results"]},
            )
            self.db.commit()
            refreshed = get_task(self.db, task.id)
            if refreshed:
                publish_task_snapshot(refreshed)
            state["completion_summary"] = completion_summary
            return self._sync_state(task, state)

        update_task_graph_metadata(self.db, task, status="running", active_node_id=None)
        set_task_graph_active_node(self.db, task, node_id=None)
        set_task_status(
            self.db,
            task,
            status=TaskStatus.RUNNING,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            error=task.error if has_failure else None,
            result={"results": state["results"]},
        )
        self.db.commit()
        refreshed = get_task(self.db, task.id)
        if refreshed:
            publish_task_snapshot(refreshed)
        return self._sync_state(task, state)

    def _next_execution_node(self, task_graph: dict[str, Any]) -> dict[str, Any] | None:
        for node in task_graph.get("nodes", []):
            if node.get("agent") != "ExecutionAgent":
                continue
            if node.get("status") not in {"pending", "waiting_for_human"}:
                continue
            if self._dependencies_met(task_graph, node):
                return node
        return None

    def _next_review_node(self, task_graph: dict[str, Any]) -> dict[str, Any] | None:
        for node in task_graph.get("nodes", []):
            if node.get("agent") != "ReviewAgent":
                continue
            if node.get("status") != "pending":
                continue
            if self._dependencies_met(task_graph, node):
                return node
        return None

    def _dependencies_met(self, task_graph: dict[str, Any], node: dict[str, Any]) -> bool:
        nodes_by_id = {item.get("id"): item for item in task_graph.get("nodes", [])}
        return all(nodes_by_id.get(dep, {}).get("status") == "completed" for dep in node.get("depends_on", []))

    def _planner_iteration_count(self, task_graph: dict[str, Any]) -> int:
        return sum(1 for node in task_graph.get("nodes", []) if node.get("agent") == "PlannerAgent")

    def _planner_node_for_iteration(self, task_graph: dict[str, Any], iteration: int) -> dict[str, Any] | None:
        return next(
            (
                node
                for node in task_graph.get("nodes", [])
                if node.get("agent") == "PlannerAgent" and int(node.get("iteration") or 0) == iteration
            ),
            None,
        )

    def _execution_nodes_for_iteration(self, task_graph: dict[str, Any], iteration: int) -> list[dict[str, Any]]:
        return [
            node
            for node in task_graph.get("nodes", [])
            if node.get("agent") == "ExecutionAgent" and int(node.get("iteration") or 0) == iteration
        ]

    def _db_step_for_execution_node(self, task, execution_node: dict[str, Any]):
        step_position = execution_node.get("step_position")
        if not isinstance(step_position, int):
            return None
        return next((step for step in task.steps if step.position == step_position), None)

    def _sync_state(self, task, state: GraphAgentState) -> GraphAgentState:
        task_graph = get_task_graph(task)
        state["task_graph"] = task_graph
        state["current_node_id"] = task_graph.get("active_node_id")
        state["error"] = task.error
        return state

    def _route_after_planner(self, state: GraphAgentState):
        task_graph = state["task_graph"]
        if task_graph.get("status") in {"completed", "failed"}:
            return END
        if self._next_execution_node(task_graph) is not None:
            return "execution_agent"
        if self._next_review_node(task_graph) is not None:
            return "review_agent"
        return END

    def _route_after_execution(self, state: GraphAgentState):
        if state["awaiting_approval"]:
            return END
        if self._next_review_node(state["task_graph"]) is not None:
            return "review_agent"
        return END

    def _route_after_review(self, state: GraphAgentState):
        task_graph = state["task_graph"]
        if state["awaiting_approval"] or task_graph.get("status") in {"completed", "failed"}:
            return END
        return "planner_agent"

    def _tool_name_for_step(self, step: ExecutionStepModel) -> str:
        if step.kind == "shell":
            return "shell.execute"
        if step.kind == "docker":
            return "docker.run"
        return "github.action"

    def _tool_call_for_step(self, step: ExecutionStepModel) -> dict[str, Any]:
        if step.kind == "shell":
            return {"title": step.title, "command": step.command or ""}
        if step.kind == "docker":
            return {
                "title": step.title,
                "image": step.image or "python:3.10-slim",
                "command": step.command,
            }
        action = (step.parameters or {}).get("action") or self.runtime.infer_github_action(step) or "github_action"
        parameters = dict(step.parameters or {})
        parameters.pop("action", None)
        return {"title": step.title, "action": action, "parameters": parameters}

    def _step_from_graph_node(self, node: dict[str, Any]) -> ExecutionStepModel:
        tool_call = dict(node.get("tool_call") or {})
        tool_name = node.get("tool_name")
        if tool_name == "shell.execute":
            return ExecutionStepModel(title=node["title"], kind="shell", command=tool_call.get("command"))
        if tool_name == "docker.run":
            return ExecutionStepModel(
                title=node["title"],
                kind="docker",
                image=tool_call.get("image"),
                command=tool_call.get("command"),
            )
        return ExecutionStepModel(
            title=node["title"],
            kind="github",
            parameters={"action": tool_call.get("action"), **dict(tool_call.get("parameters") or {})},
        )
