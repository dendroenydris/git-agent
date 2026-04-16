from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import AppSettings
from backend.app.models.enums import ApprovalMode


def get_or_create_app_settings(db: Session) -> AppSettings:
    settings = db.scalar(select(AppSettings).where(AppSettings.id == "global"))
    if settings is not None:
        return settings

    settings = AppSettings(id="global", approval_mode=ApprovalMode.NO)
    db.add(settings)
    db.flush()
    return settings


def update_app_settings(db: Session, *, approval_mode: ApprovalMode) -> AppSettings:
    settings = get_or_create_app_settings(db)
    settings.approval_mode = approval_mode
    db.add(settings)
    db.flush()
    return settings
