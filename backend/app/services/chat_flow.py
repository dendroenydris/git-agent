from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.models.enums import MessageType, TaskStatus
from backend.app.schemas import ChatAccepted, ChatAnswer
from backend.app.services.activity import publish_message_added, publish_task_snapshot
from backend.app.services.dialogs import add_message, get_dialog
from backend.app.services.request_router import decide_route_mode
from backend.app.services.search_answer import answer_with_repository_context
from backend.app.services.tasks import create_task_run, get_task
from backend.app.workers.jobs import process_task


def submit_dialog_chat(db: Session, *, dialog_id: str, user_message: str) -> ChatAccepted | ChatAnswer:
    dialog = get_dialog(db, dialog_id)
    if dialog is None:
        raise ValueError("Dialog not found")

    saved_user_message = add_message(
        db,
        dialog_id=dialog.id,
        content=user_message,
        message_type=MessageType.USER,
    )
    publish_message_added(saved_user_message, dialog_id=dialog.id)

    route_mode = decide_route_mode(user_message)
    if route_mode == "task":
        task = create_task_run(
            db,
            dialog_id=dialog.id,
            repository_id=dialog.repository_id,
            user_message=user_message,
        )
        db.commit()
        refreshed_task = get_task(db, task.id)
        if refreshed_task:
            publish_task_snapshot(refreshed_task, event_type="task_created")
        process_task.delay(task.id)
        return ChatAccepted(
            mode="task",
            task_id=task.id,
            dialog_id=dialog.id,
            status=TaskStatus.QUEUED,
        )

    loading_message = add_message(
        db,
        dialog_id=dialog.id,
        content="Searching the repository...",
        message_type=MessageType.SYSTEM,
    )
    db.commit()
    publish_message_added(loading_message, dialog_id=dialog.id)

    answer = answer_with_repository_context(db=db, dialog=dialog, user_message=user_message)
    agent_message = add_message(
        db,
        dialog_id=dialog.id,
        content=answer,
        message_type=MessageType.AGENT,
    )
    db.commit()
    publish_message_added(agent_message, dialog_id=dialog.id)
    return ChatAnswer(mode="answer", dialog_id=dialog.id, answer=answer)
