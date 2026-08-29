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
    """人工创建项目记忆时的请求体。"""

    # 新记忆的业务分类。
    kind: MemoryKindValue = "note"
    # 非空且不超过 2000 字符的记忆正文。
    content: str = Field(min_length=1, max_length=2_000)
    # 是否优先将该条目装载到运行上下文。
    pinned: bool = False
    # 可选的已完成来源运行 ID；提供时表示从运行结果确认保存。
    source_run_id: UUID | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        """拒绝只含空白字符的记忆正文。

        :param value: 客户端提交的正文。
        :return: 保留原格式的非空正文。
        :raises ValueError: 正文只包含空白字符。
        """

        if not value.strip():
            raise ValueError("content may not be blank")
        return value


class WorkspaceMemoryUpdateRequest(ApiModel):
    """部分更新项目记忆时允许提交的字段。"""

    # 新业务分类；None 表示不修改。
    kind: MemoryKindValue | None = None
    # 新正文；None 表示不修改。
    content: str | None = Field(default=None, min_length=1, max_length=2_000)
    # 新置顶状态；None 表示不修改。
    pinned: bool | None = None
    # 新启用状态；None 表示不修改。
    enabled: bool | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str | None) -> str | None:
        """拒绝更新请求中的纯空白正文。

        :param value: 新正文或表示未修改的 None。
        :return: 校验通过的原值。
        :raises ValueError: 正文只包含空白字符。
        """

        if value is not None and not value.strip():
            raise ValueError("content may not be blank")
        return value

    @model_validator(mode="after")
    def at_least_one_change(self) -> "WorkspaceMemoryUpdateRequest":
        """确保请求至少更新一个记忆字段。

        :return: 校验通过的当前请求模型。
        :raises ValueError: 所有可更新字段均为 None。
        """

        if all(value is None for value in (self.kind, self.content, self.pinned, self.enabled)):
            raise ValueError("at least one memory field must be updated")
        return self


class WorkspaceMemoryResponse(ApiModel):
    """返回给客户端的项目记忆条目。"""

    # 记忆 ID。
    id: UUID
    # 所属工作区 ID。
    workspace_id: UUID
    # 业务分类。
    kind: MemoryKindValue
    # 记忆正文。
    content: str
    # 人工或运行结果来源。
    source: MemorySourceValue
    # 自动记忆关联的来源运行 ID。
    source_run_id: UUID | None = None
    # 是否置顶。
    pinned: bool
    # 是否允许用于上下文。
    enabled: bool
    # 创建时间。
    created_at: datetime
    # 最近更新时间。
    updated_at: datetime


class WorkspaceMemoryListResponse(ApiModel):
    """工作区记忆列表响应。"""

    # 按置顶和更新时间排序的记忆集合。
    items: list[WorkspaceMemoryResponse]


class WorkspaceMemoryPurgeResponse(ApiModel):
    """清空工作区记忆后的结果。"""

    # 实际软删除的条目数量。
    deleted_count: int = Field(ge=0)


__all__ = [
    "WorkspaceMemoryCreateRequest",
    "WorkspaceMemoryListResponse",
    "WorkspaceMemoryPurgeResponse",
    "WorkspaceMemoryResponse",
    "WorkspaceMemoryUpdateRequest",
]
