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
    """在已有会话中启动 Agent 运行的请求体。"""

    # 本次交给 Agent 的用户任务正文。
    content: str = Field(min_length=1, max_length=100_000)
    # 本次运行采用的命令权限模式。
    permission_mode: PermissionModeValue
    # 本次运行是否装载项目记忆。
    use_memory: bool = True
    # 客户端生成、用于安全重试的幂等请求 ID。
    client_request_id: UUID

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        """拒绝只含空白字符的任务正文。

        :param value: 客户端提交的任务文本。
        :return: 保留原格式的非空任务文本。
        :raises ValueError: 文本只包含空白字符。
        """

        if not value.strip():
            raise ValueError("content may not be blank")
        return value


class RunResponse(ApiModel):
    """Agent 运行的当前持久化投影。"""

    # 运行 ID。
    id: UUID
    # 所属会话 ID。
    conversation_id: UUID
    # 作用工作区 ID。
    workspace_id: UUID
    # 实际权限模式。
    permission_mode: PermissionModeValue
    # 是否使用项目记忆。
    use_memory: bool
    # 当前运行状态。
    status: RunStatusValue
    # 实际使用的模型名称。
    model: str
    # 成功完成时的最终助手文本。
    final_content: str | None = None
    # 正常终止或取消原因。
    reason: str | None = None
    # 失败时经过清洗的错误码和说明。
    error: dict[str, str] | None = None
    # token、模型调用和工具调用计数。
    usage: dict[str, int] = Field(default_factory=dict)
    # 当前待处理审批的安全展示数据。
    pending_approval: dict[str, Any] | None = None
    # 运行记录创建时间。
    created_at: datetime
    # 实际开始执行时间。
    started_at: datetime | None = None
    # 进入终态的时间。
    finished_at: datetime | None = None


class RunEventResponse(ApiModel):
    """可通过 SSE 推送和断线重放的安全运行事件。"""

    # 事件在运行内的一基序号。
    seq: int = Field(ge=1)
    # 稳定事件类型名称。
    event: str
    # 事件发生时间。
    timestamp: datetime
    # 针对该事件类型白名单化的数据。
    data: dict[str, Any]


class ApprovalDecisionRequest(ApiModel):
    """用户对待处理危险操作作出的决定。"""

    # 同意执行或拒绝执行。
    decision: Literal["approve", "reject"]


class ApprovalDecisionResponse(ApiModel):
    """审批决定被服务端接受后的确认。"""

    # 审批所属运行 ID。
    run_id: UUID
    # 已处理的审批 ID。
    approval_id: UUID
    # 服务端接受的决定。
    decision: Literal["approve", "reject"]
    # 请求是否已被成功接受。
    accepted: bool = True


__all__ = [
    "ConversationRunCreateRequest",
    "ApprovalDecisionRequest",
    "ApprovalDecisionResponse",
    "RunResponse",
    "RunStatusValue",
    "RunEventResponse",
]
