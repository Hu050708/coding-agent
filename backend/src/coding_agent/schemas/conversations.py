"""定义会话资源经过校验的请求与响应结构。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PermissionModeValue = Literal["ask", "agent", "workspace_full"]
ConversationRoleValue = Literal["user", "assistant"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationCreateRequest(ApiModel):
    workspace_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=160)
    default_permission_mode: PermissionModeValue = "agent"
    use_memory: bool = True

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("title may not be blank")
        return normalized


class ConversationUpdateRequest(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    default_permission_mode: PermissionModeValue | None = None
    use_memory: bool | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("title may not be blank")
        return normalized

    @model_validator(mode="after")
    def at_least_one_change(self) -> "ConversationUpdateRequest":
        if self.title is None and self.default_permission_mode is None and self.use_memory is None:
            raise ValueError("at least one conversation field must be updated")
        return self


class ConversationResponse(ApiModel):
    id: UUID
    workspace_id: UUID
    title: str
    default_permission_mode: PermissionModeValue
    use_memory: bool
    active_run_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(ApiModel):
    items: list[ConversationResponse]


class MessageResponse(ApiModel):
    id: UUID
    conversation_id: UUID
    run_id: UUID | None = None
    seq: int = Field(ge=1)
    role: ConversationRoleValue
    content: str
    created_at: datetime


class MessageListResponse(ApiModel):
    items: list[MessageResponse]


__all__ = [
    "ConversationCreateRequest",
    "ConversationListResponse",
    "ConversationResponse",
    "ConversationRoleValue",
    "ConversationUpdateRequest",
    "MessageListResponse",
    "MessageResponse",
    "PermissionModeValue",
]
