from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.entities import TaskRun, TaskStep
from backend.app.models.enums import ApprovalStatus, StepStatus, TaskStatus
from backend.app.schemas import TaskRead, TaskStepRead


def create_task_run(
    db: Session,
    *,
    dialog_id: str,
    repository_id: str | None,
    user_message: str,
) -> TaskRun:
    task = TaskRun(
        dialog_id=dialog_id,
        repository_id=repository_id,
        user_message=user_message,
        status=TaskStatus.QUEUED,
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )
    db.add(task)
    db.flush()
    return task


def get_task(db: Session, task_id: str) -> TaskRun | None:
    statement = (
        select(TaskRun)
        .where(TaskRun.id == task_id)
        .options(selectinload(TaskRun.steps), selectinload(TaskRun.messages))
    )
    return db.scalar(statement)


def list_tasks(db: Session, dialog_id: str | None = None) -> list[TaskRun]:
    statement = select(TaskRun).options(selectinload(TaskRun.steps)).order_by(desc(TaskRun.created_at))
    if dialog_id:
        statement = statement.where(TaskRun.dialog_id == dialog_id)
    return list(db.scalars(statement).unique())


def set_task_status(
    db: Session,
    task: TaskRun,
    *,
    status: TaskStatus,
    approval_status: ApprovalStatus | None = None,
    summary: str | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> TaskRun:
    task.status = status
    if approval_status is not None:
        task.approval_status = approval_status
    if summary is not None:
        task.summary = summary
    if error is not None:
        task.error = error
    if result is not None:
        task.result_json = deepcopy(result)
    if status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        task.completed_at = datetime.utcnow()
    db.add(task)
    db.flush()
    return task


def replace_plan(db: Session, task: TaskRun, plan_payload: dict[str, Any]) -> TaskRun:
    task.plan_json = deepcopy(plan_payload)
    task.steps.clear()
    db.flush()

    for index, step_payload in enumerate(plan_payload.get("steps", []), start=1):
        task.steps.append(
            TaskStep(
                position=index,
                title=step_payload["title"],
                status=StepStatus.PENDING,
                kind=step_payload.get("kind", "plan"),
                command=step_payload.get("command"),
                metadata_json=step_payload,
                requires_approval=step_payload.get("requires_approval", False),
            )
        )

    db.add(task)
    db.flush()
    return task


def merge_plan_state(
    db: Session,
    task: TaskRun,
    *,
    intent: dict[str, Any] | None = None,
    repository_context: dict[str, Any] | None = None,
    planner_iteration: dict[str, Any] | None = None,
    react_trace_entries: list[dict[str, Any]] | None = None,
) -> TaskRun:
    plan_json = deepcopy(task.plan_json or {})
    plan_json.setdefault("steps", [])
    plan_json.setdefault("planner_iterations", [])
    plan_json.setdefault("react_trace", [])

    if intent is not None:
        plan_json["intent"] = intent
    if repository_context is not None:
        plan_json["repository_context"] = repository_context
    if planner_iteration is not None:
        plan_json["planner_iterations"].append(planner_iteration)
    if react_trace_entries:
        plan_json["react_trace"].extend(deepcopy(react_trace_entries))

    task.plan_json = plan_json
    db.add(task)
    db.flush()
    return task


def get_task_graph(task: TaskRun) -> dict[str, Any]:
    plan_json = deepcopy(task.plan_json or {})
    task_graph = deepcopy(plan_json.get("task_graph") or {})
    task_graph.setdefault("nodes", [])
    task_graph.setdefault("edges", [])
    task_graph.setdefault("active_node_id", None)
    task_graph.setdefault("worktree_path", None)
    task_graph.setdefault("base_repo_path", None)
    task_graph.setdefault("status", "pending")
    return task_graph


def set_task_graph(db: Session, task: TaskRun, *, task_graph: dict[str, Any]) -> TaskRun:
    plan_json = deepcopy(task.plan_json or {})
    normalized_graph = deepcopy(task_graph)
    normalized_graph.setdefault("nodes", [])
    normalized_graph.setdefault("edges", [])
    normalized_graph.setdefault("active_node_id", None)
    normalized_graph.setdefault("worktree_path", None)
    normalized_graph.setdefault("base_repo_path", None)
    normalized_graph.setdefault("status", "pending")
    plan_json["task_graph"] = normalized_graph
    task.plan_json = plan_json
    db.add(task)
    db.flush()
    return task


def initialize_task_graph(
    db: Session,
    task: TaskRun,
    *,
    nodes: list[dict[str, Any]],
    active_node_id: str | None,
    worktree_path: str | None,
    base_repo_path: str | None,
    edges: list[dict[str, Any]] | None = None,
    status: str = "pending",
) -> TaskRun:
    return set_task_graph(
        db,
        task,
        task_graph={
            "nodes": deepcopy(nodes),
            "edges": deepcopy(edges or []),
            "active_node_id": active_node_id,
            "worktree_path": worktree_path,
            "base_repo_path": base_repo_path,
            "status": status,
        },
    )


def update_task_graph_node(db: Session, task: TaskRun, *, node_id: str, **fields: Any) -> TaskRun:
    task_graph = get_task_graph(task)
    updated_nodes: list[dict[str, Any]] = []
    found = False
    for node in task_graph["nodes"]:
        if node.get("id") == node_id:
            updated_nodes.append({**deepcopy(node), **deepcopy(fields)})
            found = True
        else:
            updated_nodes.append(deepcopy(node))
    if not found:
        updated_nodes.append({"id": node_id, **deepcopy(fields)})
    task_graph["nodes"] = updated_nodes
    return set_task_graph(db, task, task_graph=task_graph)


def set_task_graph_active_node(db: Session, task: TaskRun, *, node_id: str | None) -> TaskRun:
    task_graph = get_task_graph(task)
    task_graph["active_node_id"] = node_id
    return set_task_graph(db, task, task_graph=task_graph)


def update_task_graph_metadata(db: Session, task: TaskRun, **fields: Any) -> TaskRun:
    task_graph = get_task_graph(task)
    for key, value in fields.items():
        task_graph[key] = deepcopy(value)
    return set_task_graph(db, task, task_graph=task_graph)


def append_replan_request(db: Session, task: TaskRun, *, failure_message: str) -> TaskRun:
    plan_json = deepcopy(task.plan_json or {})
    plan_json.setdefault("replan_requests", [])
    plan_json.setdefault("react_trace", [])

    request_index = len(plan_json["replan_requests"]) + 1
    request_payload = {
        "request": request_index,
        "failure_message": failure_message,
        "created_at": datetime.utcnow().isoformat(),
    }
    plan_json["replan_requests"].append(request_payload)
    plan_json["react_trace"].append(
        {
            "type": "observation",
            "label": f"Obs R{request_index}",
            "iteration": None,
            "step_position": None,
            "title": "Operator requested replanning",
            "status": "replan_requested",
            "created_at": request_payload["created_at"],
            "content_truncated": False,
            "content": failure_message,
        }
    )

    task.plan_json = plan_json
    db.add(task)
    db.flush()
    return task


def append_plan_steps(db: Session, task: TaskRun, steps_payload: list[dict[str, Any]]) -> TaskRun:
    if not steps_payload:
        return task

    plan_json = deepcopy(task.plan_json or {})
    existing_plan_steps = list(plan_json.get("steps", []))
    next_position = len(task.steps) + 1

    for step_payload in steps_payload:
        normalized_payload = deepcopy(step_payload)
        existing_plan_steps.append(normalized_payload)
        task.steps.append(
            TaskStep(
                position=next_position,
                title=normalized_payload["title"],
                status=StepStatus.PENDING,
                kind=normalized_payload.get("kind", "shell"),
                command=normalized_payload.get("command"),
                metadata_json=normalized_payload,
                requires_approval=normalized_payload.get("requires_approval", True),
            )
        )
        next_position += 1

    plan_json["steps"] = existing_plan_steps
    task.plan_json = plan_json
    db.add(task)
    db.flush()
    return task


def update_step(
    db: Session,
    task: TaskRun,
    *,
    position: int,
    status: StepStatus,
    output: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskStep:
    step = next((item for item in task.steps if item.position == position), None)
    if step is None:
        raise ValueError(f"Task step {position} not found for task {task.id}")

    step.status = status
    if output is not None:
        step.output = output
    if error is not None:
        step.error = error
    if metadata is not None:
        step.metadata_json = {**deepcopy(step.metadata_json or {}), **deepcopy(metadata)}

    task.current_step_index = max(task.current_step_index, position)
    db.add(step)
    db.add(task)
    db.flush()
    return step


def task_to_read(task: TaskRun) -> TaskRead:
    return TaskRead(
        id=task.id,
        dialog_id=task.dialog_id,
        repository_id=task.repository_id,
        user_message=task.user_message,
        status=task.status,
        approval_status=task.approval_status,
        plan_json=task.plan_json or {},
        result_json=task.result_json or {},
        summary=task.summary,
        error=task.error,
        current_step_index=task.current_step_index,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        steps=[TaskStepRead.model_validate(step) for step in task.steps],
    )
