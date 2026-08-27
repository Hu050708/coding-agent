from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from coding_agent.api.dependencies import get_run_manager, get_settings
from coding_agent.api.schemas import HealthResponse
from coding_agent.config import AppSettings
from coding_agent.runs.run_manager import RunManager


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(
    manager: RunManager = Depends(get_run_manager),
    settings: AppSettings = Depends(get_settings),
) -> dict[str, object]:
    return {
        "status": "ok" if manager.ready else "degraded",
        "service": "coding-agent-web",
        "api_key_configured": manager.ready,
        "model": manager.model,
        "allowed_root": os.fspath(settings.allowed_root),
        "max_active_runs": manager.max_active_runs,
        "active_runs": manager.active_runs,
        "max_model_calls": settings.max_model_calls,
        "max_tool_calls": settings.max_tool_calls,
        "max_total_tokens": settings.max_total_tokens,
        "wall_time_seconds": settings.wall_time_seconds,
    }


__all__ = ["router"]
