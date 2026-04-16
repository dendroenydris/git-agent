from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from redis import Redis

from backend.app.core.config import get_settings
from backend.app.db.session import engine, get_db, init_database
from backend.app.models.enums import ApprovalStatus, MessageType, TaskStatus
from backend.app.rag.indexer import RepositoryIndexer
from backend.app.schemas import (
    ApprovalRequest,
    AppSettingsRead,
    AppSettingsUpdate,
    ChatAnswer,
    ChatAccepted,
    ChatRequest,
    DialogCreate,
    DialogRead,
    HealthResponse,
    ReplanTaskRequest,
    RepositoryIndexRead,
    TaskActionResponse,
    TaskEvent,
    TaskRead,
)
from backend.app.services.app_settings import get_or_create_app_settings, update_app_settings
from backend.app.services.activity import publish_message_added, publish_task_snapshot
from backend.app.services.chat_flow import submit_dialog_chat
from backend.app.services.dialogs import add_message, create_dialog, dialog_to_read, get_dialog, list_dialogs
from backend.app.services.event_bus import manager, subscriber
from backend.app.services.tasks import (
    append_replan_request,
    get_task,
    list_tasks,
    set_task_status,
    task_to_read,
)
from backend.app.workers.jobs import resume_task


settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    init_database()
    await subscriber.start()
    yield
    await subscriber.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description="Agentic RAG system for GitHub automation and DevOps workflows.",
        lifespan=_app_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", response_model=dict)
    def root() -> dict:
        return {"message": settings.app_name}

    @app.get("/health", response_model=HealthResponse)
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

    @app.post("/api/dialogs", response_model=DialogRead)
    def create_dialog_endpoint(payload: DialogCreate, db: Session = Depends(get_db)) -> DialogRead:
        dialog = create_dialog(db, owner=payload.owner, name=payload.name, branch=payload.branch)
        db.commit()
        db.refresh(dialog)
        hydrated = get_dialog(db, dialog.id)
        assert hydrated is not None
        return dialog_to_read(hydrated)

    @app.get("/api/dialogs", response_model=list[DialogRead])
    def list_dialogs_endpoint(db: Session = Depends(get_db)) -> list[DialogRead]:
        return [dialog_to_read(dialog) for dialog in list_dialogs(db)]

    @app.get("/api/dialogs/{dialog_id}", response_model=DialogRead)
    def get_dialog_endpoint(dialog_id: str, db: Session = Depends(get_db)) -> DialogRead:
        dialog = get_dialog(db, dialog_id)
        if dialog is None:
            raise HTTPException(status_code=404, detail="Dialog not found")
        return dialog_to_read(dialog)

    @app.get("/api/settings", response_model=AppSettingsRead)
    def get_settings_endpoint(db: Session = Depends(get_db)) -> AppSettingsRead:
        app_settings = get_or_create_app_settings(db)
        db.commit()
        return AppSettingsRead(approval_mode=app_settings.approval_mode)

    @app.put("/api/settings", response_model=AppSettingsRead)
    def update_settings_endpoint(payload: AppSettingsUpdate, db: Session = Depends(get_db)) -> AppSettingsRead:
        app_settings = update_app_settings(db, approval_mode=payload.approval_mode)
        db.commit()
        return AppSettingsRead(approval_mode=app_settings.approval_mode)

    @app.post("/api/dialogs/{dialog_id}/chat", response_model=ChatAccepted | ChatAnswer)
    def submit_chat(dialog_id: str, payload: ChatRequest, db: Session = Depends(get_db)) -> ChatAccepted | ChatAnswer:
        try:
            return submit_dialog_chat(db, dialog_id=dialog_id, user_message=payload.message)
        except ValueError:
            raise HTTPException(status_code=404, detail="Dialog not found")

    @app.get("/api/tasks", response_model=list[TaskRead])
    def list_tasks_endpoint(
        dialog_id: str | None = None, db: Session = Depends(get_db)
    ) -> list[TaskRead]:
        return [task_to_read(task) for task in list_tasks(db, dialog_id=dialog_id)]

    @app.get("/api/tasks/{task_id}", response_model=TaskRead)
    def get_task_endpoint(task_id: str, db: Session = Depends(get_db)) -> TaskRead:
        task = get_task(db, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_to_read(task)

    @app.post("/api/tasks/{task_id}/approval", response_model=TaskActionResponse)
    def task_approval(
        task_id: str, payload: ApprovalRequest, db: Session = Depends(get_db)
    ) -> TaskActionResponse:
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

    @app.post("/api/tasks/{task_id}/replan", response_model=TaskActionResponse)
    def task_replan(
        task_id: str, payload: ReplanTaskRequest, db: Session = Depends(get_db)
    ) -> TaskActionResponse:
        task = get_task(db, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if not payload.failure_message.strip():
            raise HTTPException(status_code=400, detail="failure_message is required")

        append_replan_request(db, task, failure_message=payload.failure_message.strip())
        system_message = add_message(
            db,
            dialog_id=task.dialog_id,
            content=f"Operator requested replanning after failure:\n{payload.failure_message.strip()}",
            message_type=MessageType.SYSTEM,
            task_id=task.id,
            summary="Replan requested",
            metadata={"failure_message": payload.failure_message.strip()},
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

    @app.post("/api/repositories/{dialog_id}/index", response_model=RepositoryIndexRead)
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

    @app.get("/api/tools")
    def list_tools() -> dict:
        return {
            "tools": [
                {
                    "name": "shell.execute",
                    "description": "Run a shell command in the repository workspace",
                },
                {
                    "name": "docker.run",
                    "description": "Run a containerized command for validation or build steps",
                },
                {
                    "name": "github.create_issue_comment",
                    "description": "Create an issue or PR comment using a PAT",
                },
                {
                    "name": "github.dispatch_workflow",
                    "description": "Trigger a GitHub Actions workflow dispatch",
                },
            ]
        }

    @app.websocket("/ws/{dialog_id}")
    async def websocket_endpoint(websocket: WebSocket, dialog_id: str, db: Session = Depends(get_db)) -> None:
        dialog = get_dialog(db, dialog_id)
        if dialog is None:
            await websocket.close(code=1008, reason="Dialog not found")
            return

        await manager.connect(dialog_id, websocket)
        try:
            while True:
                raw_message = await websocket.receive_text()
                payload = json.loads(raw_message)
                if payload.get("type") != "user_message":
                    await websocket.send_text(
                        TaskEvent(type="error", dialog_id=dialog_id, payload={"message": "Unsupported event"}).model_dump_json()
                    )
                    continue

                message = payload.get("content", "").strip()
                if not message:
                    await websocket.send_text(
                        TaskEvent(type="error", dialog_id=dialog_id, payload={"message": "Empty message"}).model_dump_json()
                    )
                    continue

                # Keep the websocket path on the same submit flow as REST until the DB layer goes fully async.
                submit_chat(dialog_id, ChatRequest(message=message), db)
        except WebSocketDisconnect:
            manager.disconnect(dialog_id, websocket)
        except Exception as exc:
            logger.exception("WebSocket failure for dialog %s", dialog_id)
            manager.disconnect(dialog_id, websocket)
            await websocket.close(code=1011, reason=str(exc))

    return app


app = create_app()
