"""定义系统健康检查数据模型。"""

from __future__ import annotations

from typing import Literal

from .base import ApiModel


class HealthResponse(ApiModel):
    """Web 服务健康检查响应。"""

    # 总体健康状态。
    status: Literal["ok", "degraded"]
    # 固定服务标识。
    service: Literal["coding-agent-web"] = "coding-agent-web"
    # 数据库是否可用。
    database: Literal["ready", "unavailable"]
    # 模型供应商密钥是否已配置。
    provider_configured: bool
    # 当前配置的模型名称。
    model: str
    # 可安全展示的允许工作区根目录标签。
    allowed_root_label: str
__all__ = ["HealthResponse"]
