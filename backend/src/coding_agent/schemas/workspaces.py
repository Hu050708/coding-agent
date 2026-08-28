"""定义工作区目录管理和文件夹浏览的数据模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceCreateRequest(ApiModel):
    path: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("path")
    @classmethod
    def path_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("path may not be blank")
        return value.strip()

    @field_validator("display_name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name may not be blank")
        return normalized


class WorkspaceResponse(ApiModel):
    id: UUID
    display_name: str
    path_hint: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class WorkspaceListResponse(ApiModel):
    items: list[WorkspaceResponse]


class DirectoryEntryResponse(ApiModel):
    name: str
    path: str
    selectable: bool = True


class DirectoryBrowseResponse(ApiModel):
    current_path: str
    parent_path: str | None = None
    allowed_root: str
    entries: list[DirectoryEntryResponse]


__all__ = [
    "DirectoryBrowseResponse",
    "DirectoryEntryResponse",
    "WorkspaceCreateRequest",
    "WorkspaceListResponse",
    "WorkspaceResponse",
]
