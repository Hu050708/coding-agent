from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MemoryKindValue = Literal["preference", "fact", "decision", "note"]
MemorySourceValue = Literal["manual", "run_result"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryEntryResponse(ApiModel):
    id: str
    workspace: str
    kind: MemoryKindValue
    content: str
    source: MemorySourceValue
    source_run_id: str | None = None
    pinned: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(ApiModel):
    items: list[MemoryEntryResponse]


class MemoryCreateRequest(ApiModel):
    workspace: str = Field(min_length=1, max_length=1024)
    kind: MemoryKindValue
    content: str = Field(min_length=1, max_length=2_000)
    pinned: bool = False
    source_run_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("workspace")
    @classmethod
    def workspace_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspace may not be blank")
        return value.strip()

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content may not be blank")
        return value


class MemoryUpdateRequest(ApiModel):
    workspace: str = Field(min_length=1, max_length=1024)
    kind: MemoryKindValue | None = None
    content: str | None = Field(default=None, min_length=1, max_length=2_000)
    pinned: bool | None = None
    enabled: bool | None = None

    @field_validator("workspace")
    @classmethod
    def workspace_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspace may not be blank")
        return value.strip()

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("content may not be blank")
        return value

    @model_validator(mode="after")
    def at_least_one_change(self) -> "MemoryUpdateRequest":
        if all(
            value is None
            for value in (self.kind, self.content, self.pinned, self.enabled)
        ):
            raise ValueError("at least one memory field must be updated")
        return self


class MemoryPurgeRequest(ApiModel):
    workspace: str = Field(min_length=1, max_length=1024)

    @field_validator("workspace")
    @classmethod
    def workspace_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspace may not be blank")
        return value.strip()


class MemoryPurgeResponse(ApiModel):
    deleted_count: int = Field(ge=0)


__all__ = [
    "MemoryCreateRequest",
    "MemoryEntryResponse",
    "MemoryKindValue",
    "MemoryListResponse",
    "MemoryPurgeRequest",
    "MemoryPurgeResponse",
    "MemorySourceValue",
    "MemoryUpdateRequest",
]
