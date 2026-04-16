import uvicorn

from backend.app.main import app, create_app
from backend.app.workers.celery_app import celery_app

__all__ = ["app", "celery_app", "create_app"]


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")