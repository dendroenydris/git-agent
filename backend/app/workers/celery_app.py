from celery import Celery

from backend.app.core.config import get_settings


settings = get_settings()

celery_app = Celery(
    "agentic_rag",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_default_queue="celery",
    task_default_exchange="celery",
    task_default_routing_key="celery",
    task_routes={
        "backend.app.workers.jobs.*": {"queue": "celery"},
    },
)
