from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.routers.helpers import submit_chat_request
from backend.app.schemas import ChatAnswer, ChatAccepted, ChatRequest, DialogCreate, DialogRead
from backend.app.services.dialogs import create_dialog, dialog_to_read, get_dialog, list_dialogs


router = APIRouter(prefix="/api/dialogs", tags=["dialogs"])


@router.post("", response_model=DialogRead)
def create_dialog_endpoint(payload: DialogCreate, db: Session = Depends(get_db)) -> DialogRead:
    dialog = create_dialog(db, owner=payload.owner, name=payload.name, branch=payload.branch)
    db.commit()
    db.refresh(dialog)
    hydrated = get_dialog(db, dialog.id)
    assert hydrated is not None
    return dialog_to_read(hydrated)


@router.get("", response_model=list[DialogRead])
def list_dialogs_endpoint(db: Session = Depends(get_db)) -> list[DialogRead]:
    return [dialog_to_read(dialog) for dialog in list_dialogs(db)]


@router.get("/{dialog_id}", response_model=DialogRead)
def get_dialog_endpoint(dialog_id: str, db: Session = Depends(get_db)) -> DialogRead:
    dialog = get_dialog(db, dialog_id)
    if dialog is None:
        raise HTTPException(status_code=404, detail="Dialog not found")
    return dialog_to_read(dialog)


@router.post("/{dialog_id}/chat", response_model=ChatAccepted | ChatAnswer)
def submit_chat(dialog_id: str, payload: ChatRequest, db: Session = Depends(get_db)) -> ChatAccepted | ChatAnswer:
    return submit_chat_request(db=db, dialog_id=dialog_id, payload=payload)
