from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from redis import Redis

from backend.app.core.config import get_settings
from backend.app.db.session import engine, get_db
from backend.app.schemas import AppSettingsRead, AppSettingsUpdate, HealthResponse
from backend.app.services.app_settings import get_or_create_app_settings, update_app_settings


router = APIRouter()
settings = get_settings()


@router.get("/", response_model=dict)
def root() -> dict:
    return {"message": settings.app_name}


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    database_status = "healthy"
    redis_status = "healthy"

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        database_status = f"unhealthy: {exc}"

    try:
        Redis.from_url(settings.redis_url).ping()
    except Exception as exc:
        redis_status = f"unhealthy: {exc}"

    return HealthResponse(
        status="healthy" if "unhealthy" not in database_status + redis_status else "degraded",
        redis=redis_status,
        database=database_status,
    )


@router.get("/api/settings", response_model=AppSettingsRead)
def get_settings_endpoint(db: Session = Depends(get_db)) -> AppSettingsRead:
    app_settings = get_or_create_app_settings(db)
    db.commit()
    return AppSettingsRead(approval_mode=app_settings.approval_mode)


@router.put("/api/settings", response_model=AppSettingsRead)
def update_settings_endpoint(payload: AppSettingsUpdate, db: Session = Depends(get_db)) -> AppSettingsRead:
    app_settings = update_app_settings(db, approval_mode=payload.approval_mode)
    db.commit()
    return AppSettingsRead(approval_mode=app_settings.approval_mode)
