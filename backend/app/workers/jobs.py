from __future__ import annotations

import logging

from backend.app.agents.orchestrator import AgentOrchestrator
from backend.app.db.session import SessionLocal
from backend.app.models.enums import ApprovalStatus, TaskStatus
from backend.app.schemas import TaskEvent
from backend.app.services.event_bus import publish_event
from backend.app.services.tasks import get_task, set_task_status, task_to_read
from backend.app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="backend.app.workers.jobs.process_task")
def process_task(task_id: str) -> dict:
    db = SessionLocal()
    try:
        orchestrator = AgentOrchestrator(db)
        result = orchestrator.process_task(task_id)
        db.commit()
        return result
    except Exception as exc:
        logger.exception("Failed to process task %s", task_id)
        task = get_task(db, task_id)
        if task is not None:
            set_task_status(
                db,
                task,
                status=TaskStatus.FAILED,
                error=str(exc),
                approval_status=ApprovalStatus.NOT_REQUIRED,
            )
            db.commit()
            publish_event(
                TaskEvent(
                    type="task_updated",
                    dialog_id=task.dialog_id,
                    task_id=task.id,
                    payload={"task": task_to_read(task).model_dump(mode="json")},
                )
            )
        raise
    finally:
        db.close()


@celery_app.task(name="backend.app.workers.jobs.resume_task")
def resume_task(task_id: str) -> dict:
    return process_task(task_id)
