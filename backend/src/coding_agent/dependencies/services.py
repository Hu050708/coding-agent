"""从应用状态中获取 FastAPI 路由所需的共享依赖。"""

from __future__ import annotations

from fastapi import Request

from coding_agent.services import (
    ApplicationServices,
    CatalogService,
    ConversationRunService,
    WorkspaceMemoryService,
)
from coding_agent.settings import AppSettings
from coding_agent.database import Database
from coding_agent.agents.runtime.run_manager import RunManager


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def get_run_manager(request: Request) -> RunManager:
    return request.app.state.run_manager


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_application_services(request: Request) -> ApplicationServices:
    return request.app.state.services


def get_catalog_service(request: Request) -> CatalogService:
    return get_application_services(request).catalog


def get_conversation_run_service(request: Request) -> ConversationRunService:
    return get_application_services(request).runs


def get_workspace_memory_service(request: Request) -> WorkspaceMemoryService:
    return get_application_services(request).memories


__all__ = [
    "get_application_services",
    "get_catalog_service",
    "get_conversation_run_service",
    "get_database",
    "get_run_manager",
    "get_settings",
    "get_workspace_memory_service",
]
