from __future__ import annotations

from typing import Any, Literal, TypedDict


GraphNodeStatus = Literal["pending", "running", "completed", "failed", "waiting_for_human"]


class TaskGraphNode(TypedDict, total=False):
    id: str
    agent: str
    title: str
    status: GraphNodeStatus
    depends_on: list[str]
    tool_name: str | None
    tool_call: dict[str, Any]
    result_summary: str | None
    error: str | None


class GraphAgentState(TypedDict):
    task_id: str
    dialog_id: str
    owner: str
    name: str
    branch: str
    user_message: str
    repository_context: dict[str, Any]
    dialog_context: list[str]
    task_graph: dict[str, Any]
    results: list[dict[str, Any]]
    completion_summary: str
    awaiting_approval: bool
    current_node_id: str | None
    error: str | None
