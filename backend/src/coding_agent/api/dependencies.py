from __future__ import annotations

from fastapi import Request

from coding_agent.api.errors import ApiError
from coding_agent.config import AppSettings
from coding_agent.memory import MemoryService
from coding_agent.runs.run_manager import RunManager


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def get_run_manager(request: Request) -> RunManager:
    return request.app.state.run_manager


def get_memory_service(request: Request) -> MemoryService:
    service = request.app.state.memory_service
    if service is None:
        raise ApiError(
            503, "memory_store_unavailable", "Project memory storage is unavailable."
        )
    return service


__all__ = ["get_memory_service", "get_run_manager", "get_settings"]
