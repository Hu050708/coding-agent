from fastapi import APIRouter

from .health import router as health_router
from .memories import router as memories_router
from .runs import router as runs_router
from .workspaces import router as workspaces_router


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(memories_router)
api_router.include_router(runs_router)
api_router.include_router(workspaces_router)

__all__ = ["api_router"]
