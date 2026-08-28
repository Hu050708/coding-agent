"""定义会话级持久化运行及其事件的数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from .base import ApiModel
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
    "interrupted",
]


class ConversationRunCreateRequest(ApiModel):
    content: str = Field(min_length=1, max_length=100_000)
    permission_mode: PermissionModeValue
    use_memory: bool = True
    client_request_id: UUID

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content may not be blank")
        return value


class RunResponse(ApiModel):
    id: UUID
    conversation_id: UUID
    workspace_id: UUID
    permission_mode: PermissionModeValue
    use_memory: bool
    status: RunStatusValue
    model: str
    final_content: str | None = None
    reason: str | None = None
    error: dict[str, str] | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    pending_approval: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunEventResponse(ApiModel):
    seq: int = Field(ge=1)
    event: str
    timestamp: datetime
    data: dict[str, Any]


class ApprovalDecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]


class ApprovalDecisionResponse(ApiModel):
    run_id: UUID
    approval_id: UUID
    decision: Literal["approve", "reject"]
    accepted: bool = True


__all__ = [
    "ConversationRunCreateRequest",
    "ApprovalDecisionRequest",
    "ApprovalDecisionResponse",
    "RunResponse",
    "RunStatusValue",
    "RunEventResponse",
]
