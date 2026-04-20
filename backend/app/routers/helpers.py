from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.schemas import ChatAccepted, ChatAnswer, ChatRequest, TaskEvent
from backend.app.services.chat_flow import submit_dialog_chat


logger = logging.getLogger(__name__)


def submit_chat_request(*, db: Session, dialog_id: str, payload: ChatRequest) -> ChatAccepted | ChatAnswer:
    try:
        return submit_dialog_chat(db, dialog_id=dialog_id, user_message=payload.message)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Dialog not found") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Chat submission failed for dialog %s", dialog_id)
        raise HTTPException(status_code=500, detail="Chat submission failed") from exc


def build_chat_response_event(*, dialog_id: str, response: ChatAccepted | ChatAnswer) -> TaskEvent:
    event_type = "chat_accepted" if response.mode == "task" else "chat_answer"
    return TaskEvent(
        type=event_type,
        dialog_id=dialog_id,
        task_id=getattr(response, "task_id", None),
        payload={"response": response.model_dump(mode="json")},
    )
