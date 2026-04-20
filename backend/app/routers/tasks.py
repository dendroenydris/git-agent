from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.enums import ApprovalStatus, MessageType, TaskStatus
from backend.app.schemas import ApprovalRequest, ReplanTaskRequest, TaskActionResponse, TaskRead
from backend.app.services.activity import publish_message_added, publish_task_snapshot
from backend.app.services.dialogs import add_message
from backend.app.services.tasks import append_replan_request, get_task, list_tasks, set_task_status, task_to_read
from backend.app.workers.jobs import resume_task


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def list_tasks_endpoint(dialog_id: str | None = None, db: Session = Depends(get_db)) -> list[TaskRead]:
    return [task_to_read(task) for task in list_tasks(db, dialog_id=dialog_id)]


@router.get("/{task_id}", response_model=TaskRead)
def get_task_endpoint(task_id: str, db: Session = Depends(get_db)) -> TaskRead:
    task = get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_to_read(task)


@router.post("/{task_id}/approval", response_model=TaskActionResponse)
def task_approval(task_id: str, payload: ApprovalRequest, db: Session = Depends(get_db)) -> TaskActionResponse:
    task = get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    approval_status = ApprovalStatus.APPROVED if payload.approved else ApprovalStatus.REJECTED
    new_status = TaskStatus.QUEUED if payload.approved else TaskStatus.CANCELLED
    set_task_status(
        db,
        task,
        status=new_status,
        approval_status=approval_status,
        summary=payload.reason or task.summary,
    )
    db.commit()
    publish_task_snapshot(task)

    if payload.approved:
        resume_task.delay(task.id)

    return TaskActionResponse(
        task_id=task.id,
        status=task.status,
        approval_status=task.approval_status,
    )


@router.post("/{task_id}/replan", response_model=TaskActionResponse)
def task_replan(task_id: str, payload: ReplanTaskRequest, db: Session = Depends(get_db)) -> TaskActionResponse:
    task = get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not payload.failure_message.strip():
        raise HTTPException(status_code=400, detail="failure_message is required")

    failure_message = payload.failure_message.strip()
    append_replan_request(db, task, failure_message=failure_message)
    system_message = add_message(
        db,
        dialog_id=task.dialog_id,
        content=f"Operator requested replanning after failure:\n{failure_message}",
        message_type=MessageType.SYSTEM,
        task_id=task.id,
        summary="Replan requested",
        metadata={"failure_message": failure_message},
    )
    set_task_status(
        db,
        task,
        status=TaskStatus.QUEUED,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        summary="Queued for replanning after failure.",
    )
    task.error = None
    task.completed_at = None
    db.add(task)
    db.commit()

    publish_message_added(system_message, dialog_id=task.dialog_id, task_id=task.id)
    publish_task_snapshot(task)
    resume_task.delay(task.id)

    return TaskActionResponse(
        task_id=task.id,
        status=task.status,
        approval_status=task.approval_status,
    )
