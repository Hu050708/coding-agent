"""定义会话级持久化运行及其事件的数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .conversations import PermissionModeValue


PersistentRunStatusValue = Literal[
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


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class PersistentRunResponse(ApiModel):
    id: UUID
    conversation_id: UUID
    workspace_id: UUID
    permission_mode: PermissionModeValue
    use_memory: bool
    status: PersistentRunStatusValue
    model: str
    final_content: str | None = None
    reason: str | None = None
    error: dict[str, str] | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    pending_approval: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PersistentMessageResponse(ApiModel):
    id: UUID
    conversation_id: UUID
    run_id: UUID | None = None
    seq: int = Field(ge=1)
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class RunEventResponse(ApiModel):
    seq: int = Field(ge=1)
    event: str
    timestamp: datetime
    data: dict[str, Any]


class RunEventListResponse(ApiModel):
    items: list[RunEventResponse]


class PersistentApprovalDecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]


class PersistentApprovalDecisionResponse(ApiModel):
    run_id: UUID
    approval_id: UUID
    decision: Literal["approve", "reject"]
    accepted: bool = True


__all__ = [
    "ConversationRunCreateRequest",
    "PersistentApprovalDecisionRequest",
    "PersistentApprovalDecisionResponse",
    "PersistentMessageResponse",
    "PersistentRunResponse",
    "PersistentRunStatusValue",
    "RunEventListResponse",
    "RunEventResponse",
]
