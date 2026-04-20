from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.routers.helpers import build_chat_response_event, submit_chat_request
from backend.app.schemas import ChatRequest, TaskEvent
from backend.app.services.dialogs import get_dialog
from backend.app.services.event_bus import manager


logger = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])


def _validate_user_message(payload: dict, dialog_id: str) -> str:
    if payload.get("type") != "user_message":
        raise HTTPException(status_code=400, detail="Unsupported event")

    message = str(payload.get("content", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="Empty message")
    return message


async def _send_error_event(websocket: WebSocket, *, dialog_id: str, message: str) -> None:
    await websocket.send_text(TaskEvent(type="error", dialog_id=dialog_id, payload={"message": message}).model_dump_json())


@router.websocket("/ws/{dialog_id}")
async def websocket_endpoint(websocket: WebSocket, dialog_id: str, db: Session = Depends(get_db)) -> None:
    dialog = get_dialog(db, dialog_id)
    if dialog is None:
        await websocket.close(code=1008, reason="Dialog not found")
        return

    await manager.connect(dialog_id, websocket)
    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                payload = json.loads(raw_message)
                message = _validate_user_message(payload, dialog_id)
                response = submit_chat_request(
                    db=db,
                    dialog_id=dialog_id,
                    payload=ChatRequest(message=message),
                )
            except json.JSONDecodeError:
                await _send_error_event(websocket, dialog_id=dialog_id, message="Invalid JSON payload")
                continue
            except HTTPException as exc:
                await _send_error_event(websocket, dialog_id=dialog_id, message=str(exc.detail))
                continue

            await websocket.send_text(build_chat_response_event(dialog_id=dialog_id, response=response).model_dump_json())
    except WebSocketDisconnect:
        manager.disconnect(dialog_id, websocket)
    except Exception:
        logger.exception("WebSocket failure for dialog %s", dialog_id)
        manager.disconnect(dialog_id, websocket)
        await websocket.close(code=1011, reason="Internal server error")
