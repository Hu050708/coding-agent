"""定义关联到已登记工作区的记忆条目数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .base import ApiModel


MemoryKindValue = Literal["preference", "fact", "decision", "note"]
MemorySourceValue = Literal["manual", "run_result"]


class WorkspaceMemoryCreateRequest(ApiModel):
    kind: MemoryKindValue = "note"
    content: str = Field(min_length=1, max_length=2_000)
    pinned: bool = False
    source_run_id: UUID | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content may not be blank")
        return value


class WorkspaceMemoryUpdateRequest(ApiModel):
    kind: MemoryKindValue | None = None
    content: str | None = Field(default=None, min_length=1, max_length=2_000)
    pinned: bool | None = None
    enabled: bool | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("content may not be blank")
        return value

    @model_validator(mode="after")
    def at_least_one_change(self) -> "WorkspaceMemoryUpdateRequest":
        if all(value is None for value in (self.kind, self.content, self.pinned, self.enabled)):
            raise ValueError("at least one memory field must be updated")
        return self


class WorkspaceMemoryResponse(ApiModel):
    id: UUID
    workspace_id: UUID
    kind: MemoryKindValue
    content: str
    source: MemorySourceValue
    source_run_id: UUID | None = None
    pinned: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class WorkspaceMemoryListResponse(ApiModel):
    items: list[WorkspaceMemoryResponse]


class WorkspaceMemoryPurgeResponse(ApiModel):
    deleted_count: int = Field(ge=0)


__all__ = [
    "WorkspaceMemoryCreateRequest",
    "WorkspaceMemoryListResponse",
    "WorkspaceMemoryPurgeResponse",
    "WorkspaceMemoryResponse",
    "WorkspaceMemoryUpdateRequest",
]
