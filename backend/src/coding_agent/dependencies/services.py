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
    """从 FastAPI 应用状态取得不可变配置。

    :param request: 当前 HTTP 请求。
    :return: 应用启动时创建的共享配置对象。
    """

    return request.app.state.settings


def get_run_manager(request: Request) -> RunManager:
    """从应用状态取得内存运行协调器。

    :param request: 当前 HTTP 请求。
    :return: 负责活动运行、事件和审批协调的共享管理器。
    """

    return request.app.state.run_manager


def get_database(request: Request) -> Database:
    """从应用状态取得数据库生命周期封装。

    :param request: 当前 HTTP 请求。
    :return: 共享 SQLAlchemy 引擎与会话工厂。
    """

    return request.app.state.database


def get_application_services(request: Request) -> ApplicationServices:
    """从应用状态取得业务服务容器。

    :param request: 当前 HTTP 请求。
    :return: 应用启动时组装的业务服务集合。
    """

    return request.app.state.services


def get_catalog_service(request: Request) -> CatalogService:
    """取得负责工作区和会话目录的业务服务。

    :param request: 当前 HTTP 请求。
    :return: 目录业务服务。
    """

    return get_application_services(request).catalog


def get_conversation_run_service(request: Request) -> ConversationRunService:
    """取得负责消息及运行生命周期的业务服务。

    :param request: 当前 HTTP 请求。
    :return: 会话运行业务服务。
    """

    return get_application_services(request).runs


def get_workspace_memory_service(request: Request) -> WorkspaceMemoryService:
    """取得负责项目记忆管理的业务服务。

    :param request: 当前 HTTP 请求。
    :return: 工作区记忆业务服务。
    """

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
