from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.rag.indexer import RepositoryIndexer
from backend.app.schemas import RepositoryIndexRead
from backend.app.services.dialogs import get_dialog


router = APIRouter(prefix="/api/repositories", tags=["repositories"])


@router.post("/{dialog_id}/index", response_model=RepositoryIndexRead)
def index_repository(dialog_id: str, db: Session = Depends(get_db)) -> RepositoryIndexRead:
    dialog = get_dialog(db, dialog_id)
    if dialog is None or dialog.repository is None:
        raise HTTPException(status_code=404, detail="Dialog repository not found")

    snapshot = RepositoryIndexer().ingest_repository(
        db,
        owner=dialog.repository.owner,
        name=dialog.repository.name,
        branch=dialog.repository.branch,
    )
    db.commit()
    return RepositoryIndexRead.model_validate(snapshot.index)
