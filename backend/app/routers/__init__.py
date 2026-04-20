from backend.app.routers.dialogs import router as dialogs_router
from backend.app.routers.realtime import router as realtime_router
from backend.app.routers.repositories import router as repositories_router
from backend.app.routers.system import router as system_router
from backend.app.routers.tasks import router as tasks_router
from backend.app.routers.tools import router as tools_router

__all__ = [
    "dialogs_router",
    "realtime_router",
    "repositories_router",
    "system_router",
    "tasks_router",
    "tools_router",
]
