from __future__ import annotations

from typing import Any

from backend.app.schemas import TaskEvent
from backend.app.services.event_bus import publish_event
from backend.app.services.tasks import task_to_read


def publish_task_snapshot(task: Any, *, event_type: str = "task_updated", payload: dict[str, Any] | None = None) -> None:
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


def publish_message_added(message: Any, *, dialog_id: str, task_id: str | None = None) -> None:
    publish_event(
        TaskEvent(
            type="message_added",
            dialog_id=dialog_id,
            task_id=task_id,
            message_id=message.id,
            payload={
                "message": {
                    "id": message.id,
                    "type": message.type,
                    "content": message.content,
                    "created_at": message.created_at.isoformat(),
                }
            },
        )
    )
