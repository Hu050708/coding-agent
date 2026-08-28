"""定义系统健康检查数据模型。"""

from __future__ import annotations

from typing import Literal

from .base import ApiModel


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    service: Literal["coding-agent-web"] = "coding-agent-web"
    database: Literal["ready", "unavailable"]
    provider_configured: bool
    model: str
    allowed_root_label: str
__all__ = ["HealthResponse"]
