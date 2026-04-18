from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from langgraph.graph import StateGraph
from sqlalchemy.orm import Session

from backend.app.agents.planner_context import build_dialog_context
from backend.app.agents.graph_state import GraphAgentState
from backend.app.agents.orchestrator import AgentOrchestrator
from backend.app.agents.tools import GraphToolbox
from backend.app.agents.types import ExecutionStepModel
from backend.app.models.enums import ApprovalStatus, TaskStatus
from backend.app.services.activity import publish_task_snapshot
from backend.app.services.dialogs import get_dialog
from backend.app.services.tasks import (
    get_task,
    get_task_graph,
    initialize_task_graph,
    merge_plan_state,
    set_task_graph,
    set_task_graph_active_node,
    set_task_status,
    update_task_graph_metadata,
    update_task_graph_node,
)
from backend.app.services.worktree_manager import WorktreeManager


logger = logging.getLogger(__name__)


class LangGraphRunner:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.orchestrator = AgentOrchestrator(db)
        self.worktree_manager = WorktreeManager()

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
        workflow.add_edge("planner_agent", "execution_agent")
        workflow.add_edge("execution_agent", "review_agent")
        return workflow.compile()

    def _build_initial_state(self, *, task, dialog) -> GraphAgentState:
        repository_context = dict((task.plan_json or {}).get("repository_context") or {})
        task_graph = get_task_graph(task)
        return {
            "task_id": task.id,
            "dialog_id": dialog.id,
            "owner": dialog.repository.owner,
            "name": dialog.repository.name,
            "branch": dialog.repository.branch,
            "user_message": task.user_message,
            "repository_context": repository_context,
            "dialog_context": build_dialog_context(dialog.messages),
            "task_graph": task_graph,
            "results": list((task.result_json or {}).get("results", [])),
            "completion_summary": task.summary or "",
            "awaiting_approval": False,
            "current_node_id": task_graph.get("active_node_id"),
            "error": task.error,
        }

    def _planner_agent_node(self, state: GraphAgentState) -> GraphAgentState:
        task = get_task(self.db, state["task_id"])
        if task is None:
            raise ValueError(f"Task {state['task_id']} not found")

        existing_graph = get_task_graph(task)
        if existing_graph.get("nodes"):
            state["task_graph"] = existing_graph
            state["current_node_id"] = existing_graph.get("active_node_id")
            return state

        workspace = self.worktree_manager.ensure_task_worktree(
            owner=state["owner"],
            name=state["name"],
            branch=state["branch"],
            task_id=state["task_id"],
        )

        if not state["repository_context"]:
            state["repository_context"] = self.orchestrator._build_repository_context(
                owner=state["owner"],
                name=state["name"],
                branch=state["branch"],
                user_message=state["user_message"],
            )

        state["repository_context"]["worktree_path"] = workspace["worktree_path"]
        state["repository_context"]["base_repo_path"] = workspace["base_repo_path"]

        decision = self.orchestrator._plan_next_actions_with_llm(state, task)
        if decision is None:
            decision = self.orchestrator._plan_next_actions_with_rules(state, task)
        decision = self.orchestrator._normalize_decision(decision, state, task)

        planner_node_id = f"planner-{task.id}"
        action_node_id = f"execute-{task.id}"
        review_node_id = f"review-{task.id}"
        execution_nodes: list[dict[str, Any]] = []
        if decision.steps:
            step = decision.steps[0]
            execution_nodes.append(
                {
                    "id": action_node_id,
                    "agent": "ExecutionAgent",
                    "title": step.title,
                    "status": "pending",
                    "depends_on": [planner_node_id],
                    "tool_name": self._tool_name_for_step(step),
                    "tool_call": self._tool_call_for_step(step),
                    "result_summary": None,
                    "error": None,
                }
            )

        review_dependencies = [action_node_id] if execution_nodes else [planner_node_id]
        nodes = [
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
            },
            *execution_nodes,
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
            },
        ]

        initialize_task_graph(
            self.db,
            task,
            nodes=nodes,
            active_node_id=action_node_id if execution_nodes else review_node_id,
            worktree_path=workspace["worktree_path"],
            base_repo_path=workspace["base_repo_path"],
            status="running",
        )
        merge_plan_state(
            self.db,
            task,
            intent=decision.intent.model_dump(),
            repository_context=state["repository_context"],
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

        state["task_graph"] = get_task_graph(task)
        state["current_node_id"] = state["task_graph"].get("active_node_id")
        return state

    def _execution_agent_node(self, state: GraphAgentState) -> GraphAgentState:
        task = get_task(self.db, state["task_id"])
        if task is None:
            raise ValueError(f"Task {state['task_id']} not found")

        task_graph = get_task_graph(task)
        execution_node = self._next_execution_node(task_graph)
        if execution_node is None:
            state["task_graph"] = task_graph
            return state

        node_id = execution_node["id"]
        set_task_graph_active_node(self.db, task, node_id=node_id)
        update_task_graph_node(self.db, task, node_id=node_id, status="running")
        update_task_graph_metadata(self.db, task, status="running")
        self.db.commit()

        tool_step = self._step_from_graph_node(execution_node)
        if self.orchestrator._requires_approval(tool_step) and task.approval_status != ApprovalStatus.APPROVED:
            approval_message = f"Approval required before running graph node: {execution_node['title']}"
            update_task_graph_node(
                self.db,
                task,
                node_id=node_id,
                status="waiting_for_human",
                result_summary=approval_message,
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
            state["awaiting_approval"] = True
            state["task_graph"] = get_task_graph(task)
            state["current_node_id"] = node_id
            return state

        toolbox = GraphToolbox(
            self.orchestrator,
            owner=state["owner"],
            name=state["name"],
            branch=state["branch"],
            task_id=state["task_id"],
        )
        tool = toolbox.get_tool(execution_node["tool_name"])
        tool_result = tool.invoke(deepcopy(execution_node["tool_call"]))
        state["results"].append(tool_result)
        succeeded = bool(tool_result.get("success"))

        update_task_graph_node(
            self.db,
            task,
            node_id=node_id,
            status="completed" if succeeded else "failed",
            result_summary=str(tool_result.get("output") or "")[:240] or execution_node["title"],
            error=tool_result.get("error"),
        )
        set_task_status(
            self.db,
            task,
            status=TaskStatus.RUNNING,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            error=tool_result.get("error"),
            result={"results": state["results"]},
        )
        self.db.commit()
        refreshed = get_task(self.db, task.id)
        if refreshed:
            publish_task_snapshot(refreshed)
        state["task_graph"] = get_task_graph(task)
        state["current_node_id"] = node_id
        state["awaiting_approval"] = False
        return state

    def _review_agent_node(self, state: GraphAgentState) -> GraphAgentState:
        task = get_task(self.db, state["task_id"])
        if task is None:
            raise ValueError(f"Task {state['task_id']} not found")
        if state["awaiting_approval"]:
            return state

        task_graph = get_task_graph(task)
        review_node = next((node for node in task_graph["nodes"] if node.get("agent") == "ReviewAgent"), None)
        if review_node is None or review_node.get("status") == "completed":
            state["task_graph"] = task_graph
            return state

        execution_nodes = [node for node in task_graph["nodes"] if node.get("agent") == "ExecutionAgent"]
        if any(node.get("status") in {"pending", "running", "waiting_for_human"} for node in execution_nodes):
            state["task_graph"] = task_graph
            return state

        has_failure = any(node.get("status") == "failed" for node in execution_nodes)
        completion_summary = self.orchestrator._build_summary(
            state["user_message"],
            state["results"],
            completion_summary="Graph workflow completed." if not has_failure else "Graph workflow completed with failures.",
        )
        update_task_graph_node(
            self.db,
            task,
            node_id=review_node["id"],
            status="completed",
            result_summary=completion_summary,
        )
        update_task_graph_metadata(
            self.db,
            task,
            status="failed" if has_failure else "completed",
            active_node_id=None,
        )
        set_task_graph_active_node(self.db, task, node_id=None)
        set_task_status(
            self.db,
            task,
            status=TaskStatus.FAILED if has_failure else TaskStatus.COMPLETED,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            summary=completion_summary,
            error=task.error if has_failure else None,
            result={"results": state["results"]},
        )
        self.db.commit()
        refreshed = get_task(self.db, task.id)
        if refreshed:
            publish_task_snapshot(refreshed)

        state["task_graph"] = get_task_graph(task)
        state["completion_summary"] = completion_summary
        state["current_node_id"] = None
        return state

    def _next_execution_node(self, task_graph: dict[str, Any]) -> dict[str, Any] | None:
        nodes = task_graph.get("nodes", [])
        for node in nodes:
            if node.get("agent") != "ExecutionAgent":
                continue
            if node.get("status") not in {"pending", "waiting_for_human"}:
                continue
            if self._dependencies_met(task_graph, node):
                return node
        return None

    def _dependencies_met(self, task_graph: dict[str, Any], node: dict[str, Any]) -> bool:
        nodes_by_id = {item.get("id"): item for item in task_graph.get("nodes", [])}
        return all(nodes_by_id.get(dep, {}).get("status") == "completed" for dep in node.get("depends_on", []))

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
        action = (step.parameters or {}).get("action") or self.orchestrator._infer_github_action(step) or "github_action"
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
