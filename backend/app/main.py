from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.db.session import init_database
from backend.app.routers import (
    dialogs_router,
    realtime_router,
    repositories_router,
    system_router,
    tasks_router,
    tools_router,
)
from backend.app.services.event_bus import subscriber


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

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception for %s %s", request.method, request.url)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    app.include_router(system_router)
    app.include_router(dialogs_router)
    app.include_router(tasks_router)
    app.include_router(repositories_router)
    app.include_router(tools_router)
    app.include_router(realtime_router)

    return app


app = create_app()
