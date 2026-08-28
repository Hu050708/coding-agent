"""定义系统健康检查和工作区校验的数据模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    service: Literal["coding-agent-web"] = "coding-agent-web"
    database: Literal["ready", "unavailable"]
    provider_configured: bool
    model: str
    allowed_root_label: str


class WorkspaceValidateRequest(ApiModel):
    workspace: str = Field(min_length=1, max_length=1024)

    @field_validator("workspace")
    @classmethod
    def workspace_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspace may not be blank")
        return value.strip()


class WorkspaceValidateResponse(ApiModel):
    valid: Literal[True] = True
    workspace: str
    allowed_root: str


__all__ = ["HealthResponse", "WorkspaceValidateRequest", "WorkspaceValidateResponse"]
