"""提供包含模型供应商和数据库就绪状态的健康检查接口。"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from coding_agent.dependencies import get_database, get_run_manager, get_settings
from coding_agent.schemas.system import HealthResponse
from coding_agent.settings import AppSettings
from coding_agent.database import Database
from coding_agent.agents.runtime.run_manager import RunManager


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(
    manager: RunManager = Depends(get_run_manager),
    settings: AppSettings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> dict[str, object]:
    """汇总 PostgreSQL 与模型供应商的就绪状态。

    :param manager: FastAPI 注入的运行管理器，用于检查供应商配置。
    :param settings: FastAPI 注入的应用配置。
    :param database: FastAPI 注入的数据库封装。
    :return: 总体状态及各关键依赖的就绪信息。
    """

    # 第一步：主动执行轻量数据库查询，区分配置存在和连接真正可用。
    database_state = "ready"
    try:
        database.healthcheck()
    except Exception:
        database_state = "unavailable"
    # 第二步：数据库和模型都可用才报告 ok，否则保留各子系统状态并报告 degraded。
    provider_ready = manager.ready
    return {
        "status": "ok" if database_state == "ready" and provider_ready else "degraded",
        "service": "coding-agent-web",
        "database": database_state,
        "provider_configured": provider_ready,
        "model": manager.model,
        "allowed_root_label": os.fspath(settings.allowed_root),
    }


__all__ = ["router"]
