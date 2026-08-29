"""定义会话资源经过校验的请求与响应结构。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .base import ApiModel


PermissionModeValue = Literal["ask", "agent", "workspace_full"]
ConversationRoleValue = Literal["user", "assistant"]


class ConversationCreateRequest(ApiModel):
    """创建会话时允许客户端提交的字段。"""

    # 新会话所属的已登记工作区 ID。
    workspace_id: UUID
    # 可选会话标题；省略时由服务层根据首条任务生成。
    title: str | None = Field(default=None, min_length=1, max_length=160)
    # 该会话后续创建运行时的默认权限模式。
    default_permission_mode: PermissionModeValue = "agent"
    # 该会话后续运行默认是否使用项目记忆。
    use_memory: bool = True

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        """去除标题首尾空白并拒绝纯空白值。

        :param value: 客户端提交的可选标题。
        :return: None 或清理后的非空标题。
        :raises ValueError: 标题只包含空白字符。
        """

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("title may not be blank")
        return normalized


class ConversationUpdateRequest(ApiModel):
    """部分更新会话时允许提交的可选字段。"""

    # 新会话标题；None 表示不修改。
    title: str | None = Field(default=None, min_length=1, max_length=160)
    # 新默认权限模式；None 表示不修改。
    default_permission_mode: PermissionModeValue | None = None
    # 新默认记忆开关；None 表示不修改。
    use_memory: bool | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        """清理更新请求中的可选标题。

        :param value: 客户端提交的新标题或 None。
        :return: None 或去除首尾空白后的标题。
        :raises ValueError: 标题只包含空白字符。
        """

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("title may not be blank")
        return normalized

    @model_validator(mode="after")
    def at_least_one_change(self) -> "ConversationUpdateRequest":
        """确保部分更新请求至少包含一个实际变更。

        :return: 校验通过的当前请求模型。
        :raises ValueError: 所有可更新字段均为 None。
        """

        if self.title is None and self.default_permission_mode is None and self.use_memory is None:
            raise ValueError("at least one conversation field must be updated")
        return self


class ConversationResponse(ApiModel):
    """返回给客户端的会话概要。"""

    # 会话 ID。
    id: UUID
    # 所属工作区 ID。
    workspace_id: UUID
    # 用户可见标题。
    title: str
    # 默认权限模式。
    default_permission_mode: PermissionModeValue
    # 默认记忆开关。
    use_memory: bool
    # 当前活动运行 ID；没有活动运行时为 None。
    active_run_id: UUID | None = None
    # 创建时间。
    created_at: datetime
    # 最近更新时间。
    updated_at: datetime


class ConversationListResponse(ApiModel):
    """会话列表响应。"""

    # 按服务层规则排序的会话集合。
    items: list[ConversationResponse]


class MessageResponse(ApiModel):
    """一条用户可见的持久化会话消息。"""

    # 消息 ID。
    id: UUID
    # 所属会话 ID。
    conversation_id: UUID
    # 关联运行 ID；不关联具体运行时为 None。
    run_id: UUID | None = None
    # 消息在会话内的一基序号。
    seq: int = Field(ge=1)
    # 用户或助手角色。
    role: ConversationRoleValue
    # 消息正文。
    content: str
    # 持久化时间。
    created_at: datetime


class MessageListResponse(ApiModel):
    """按序号排列的消息列表响应。"""

    # 会话的用户可见消息集合。
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
