from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    service: Literal["coding-agent-web"] = "coding-agent-web"
    api_key_configured: bool
    model: str
    allowed_root: str
    max_active_runs: int = Field(ge=1)
    active_runs: int = Field(ge=0)
    max_model_calls: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    wall_time_seconds: float = Field(gt=0)


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
