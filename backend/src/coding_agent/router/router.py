"""组装后端 API 对外提供的各组 HTTP 路由。"""

from fastapi import APIRouter

from .conversations import router as conversations_router
from .evaluations import router as evaluations_router
from .health import router as health_router
from .memories import router as memories_router
from .runs import router as runs_router
from .workspaces import router as workspaces_router


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(evaluations_router)
api_router.include_router(workspaces_router)
api_router.include_router(conversations_router)
api_router.include_router(runs_router)
api_router.include_router(memories_router)

__all__ = ["api_router"]
