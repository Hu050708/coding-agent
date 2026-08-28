"""定义进程内运行、审批和用量汇总的数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .conversations import PermissionModeValue


RunStatusValue = Literal[
    "starting",
    "running",
    "waiting_approval",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
    "budget_exhausted",
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunCreateRequest(ApiModel):
    workspace: str = Field(min_length=1, max_length=1024)
    task: str = Field(min_length=1, max_length=100_000)
    use_memory: bool = True

    @field_validator("workspace")
    @classmethod
    def workspace_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspace may not be blank")
        return value.strip()

    @field_validator("task")
    @classmethod
    def task_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task may not be blank")
        return value


class UsageResponse(ApiModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    prompt_cache_hit_tokens: int = Field(default=0, ge=0)
    prompt_cache_miss_tokens: int = Field(default=0, ge=0)


class RunErrorResponse(ApiModel):
    code: str
    message: str


class PendingApprovalResponse(ApiModel):
    approval_id: str
    argv: list[str]
    cwd: str
    reason: str
    created_at: datetime
    expires_at: datetime


class MemorySummaryResponse(ApiModel):
    status: Literal["pending", "loaded", "empty", "disabled", "unavailable"]
    loaded_count: int = Field(default=0, ge=0)
    loaded_ids: list[str] = Field(default_factory=list)


class RunSummaryResponse(ApiModel):
    run_id: str
    status: RunStatusValue
    workspace: str
    permission_mode: PermissionModeValue = "agent"
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    final_content: str | None = None
    reason: str | None = None
    error: RunErrorResponse | None = None
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    usage: UsageResponse = Field(default_factory=UsageResponse)
    duration_seconds: float | None = Field(default=None, ge=0)
    memory: MemorySummaryResponse = Field(
        default_factory=lambda: MemorySummaryResponse(status="unavailable")
    )
    pending_approval: PendingApprovalResponse | None = None
    cancel_requested: bool = False


class RunListResponse(ApiModel):
    items: list[RunSummaryResponse]


class ApprovalDecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]


class ApprovalDecisionResponse(ApiModel):
    run_id: str
    approval_id: str
    decision: Literal["approve", "reject"]
    accepted: bool = True


__all__ = [
    "ApprovalDecisionRequest",
    "ApprovalDecisionResponse",
    "PendingApprovalResponse",
    "MemorySummaryResponse",
    "RunCreateRequest",
    "RunListResponse",
    "RunStatusValue",
    "RunSummaryResponse",
    "UsageResponse",
]
