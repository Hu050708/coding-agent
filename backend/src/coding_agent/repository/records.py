"""持久化事务之外返回的不可变记录值。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from coding_agent import models


def _aware(value: datetime) -> datetime:
    """确保数据库时间值包含时区信息。

    :param value: ORM 返回的时间对象。
    :return: 原有带时区值，或按 UTC 补齐的时间值。
    """

    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _optional_aware(value: datetime | None) -> datetime | None:
    """对可空数据库时间执行时区规范化。

    :param value: 可为空的 ORM 时间值。
    :return: None 或带时区时间值。
    """

    return None if value is None else _aware(value)


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    """脱离 ORM 会话后可安全传递的工作区记录。"""

    id: UUID  # 工作区 ID。
    canonical_path: str  # 经过安全校验的规范绝对路径。
    path_key: str  # 用于唯一性比较的规范路径键。
    display_name: str  # 用户可见名称。
    archived_at: datetime | None  # 归档时间。
    deleted_at: datetime | None  # 软删除时间。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 最近更新时间。


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    """脱离 ORM 会话后可安全传递的会话记录。"""

    id: UUID  # 会话 ID。
    workspace_id: UUID  # 所属工作区 ID。
    title: str  # 用户可见标题。
    default_permission_mode: str  # 新运行默认权限模式。
    use_memory: bool  # 新运行默认是否使用记忆。
    archived_at: datetime | None  # 归档时间。
    deleted_at: datetime | None  # 软删除时间。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 最近更新时间。


@dataclass(frozen=True, slots=True)
class RunRecord:
    """包含完整状态和用量投影的运行记录。"""

    id: UUID  # 运行 ID。
    workspace_id: UUID  # 作用工作区 ID。
    conversation_id: UUID  # 所属会话 ID。
    client_request_id: str  # 客户端幂等请求标识。
    permission_mode: str  # 实际权限模式。
    use_memory: bool  # 是否使用项目记忆。
    status: str  # 当前运行状态。
    model: str | None  # 实际模型名称。
    reason: str | None  # 正常终止、取消或预算原因。
    error_code: str | None  # 失败错误码。
    error_message: str | None  # 可安全展示的失败说明。
    prompt_tokens: int  # 累计输入 token 数。
    completion_tokens: int  # 累计输出 token 数。
    total_tokens: int  # 累计总 token 数。
    prompt_cache_hit_tokens: int  # 提示缓存命中 token 数。
    prompt_cache_miss_tokens: int  # 提示缓存未命中 token 数。
    model_calls: int  # 模型调用次数。
    tool_calls: int  # 工具调用次数。
    duration_ms: int | None  # 总耗时（毫秒）。
    cancel_requested_at: datetime | None  # 收到取消请求的时间。
    started_at: datetime | None  # 实际开始时间。
    finished_at: datetime | None  # 进入终态时间。
    deleted_at: datetime | None  # 软删除时间。
    created_at: datetime  # 记录创建时间。
    updated_at: datetime  # 记录更新时间。


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """带会话序号的不可变消息记录。"""

    id: UUID  # 消息 ID。
    conversation_id: UUID  # 所属会话 ID。
    run_id: UUID | None  # 可选关联运行 ID。
    seq: int  # 会话内消息序号。
    role: str  # 用户或助手角色。
    content: str  # 用户可见正文。
    created_at: datetime  # 创建时间。
    deleted_at: datetime | None  # 软删除时间。


@dataclass(frozen=True, slots=True)
class RunEventRecord:
    """带运行序号的不可变事件记录。"""

    run_id: UUID  # 所属运行 ID。
    seq: int  # 运行内事件序号。
    event: str  # 稳定事件类型。
    data: dict[str, Any]  # 白名单化事件数据。
    occurred_at: datetime  # 事件发生时间。


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """提供给应用层的不可变审批记录。"""

    id: UUID  # 审批 ID。
    run_id: UUID  # 所属运行 ID。
    status: str  # 当前审批状态。
    tool_name: str  # 待执行工具名称。
    action_summary: str  # 面向用户的操作摘要。
    reason: str  # 需要审批的原因。
    request_data: dict[str, Any]  # 可安全展示的请求字段。
    expires_at: datetime  # 自动过期时间。
    resolved_at: datetime | None  # 实际处理时间。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 最近更新时间。


@dataclass(frozen=True, slots=True)
class MemoryEntryRecord:
    """提供给应用层的不可变记忆记录。"""

    id: UUID  # 记忆 ID。
    workspace_id: UUID  # 所属工作区 ID。
    kind: str  # 业务分类。
    content: str  # 记忆正文。
    content_hash: str  # 规范化正文哈希。
    source: str  # 条目来源。
    source_run_id: UUID | None  # 可选来源运行 ID。
    pinned: bool  # 是否置顶。
    enabled: bool  # 是否允许用于上下文。
    confirmed_at: datetime  # 用户确认保存时间。
    deleted_at: datetime | None  # 软删除时间。
    created_at: datetime  # 创建时间。
    updated_at: datetime  # 最近更新时间。


@dataclass(frozen=True, slots=True)
class RunMemoryRecord:
    """提供给运行上下文的不可变记忆快照记录。"""

    run_id: UUID  # 使用该快照的运行 ID。
    position: int  # 上下文中的一基位置。
    memory_entry_id: UUID | None  # 可选原记忆条目 ID。
    kind: str  # 快照时冻结的分类。
    content: str  # 快照时冻结的正文。
    captured_at: datetime  # 捕获时间。


def workspace_record(item: models.Workspace) -> WorkspaceRecord:
    """把工作区 ORM 实体复制为会话外安全记录。

    :param item: 当前事务中的工作区实体。
    :return: 不依赖 ORM 会话的不可变记录。
    """

    return WorkspaceRecord(
        id=item.id,
        canonical_path=item.canonical_path,
        path_key=item.path_key,
        display_name=item.display_name,
        archived_at=_optional_aware(item.archived_at),
        deleted_at=_optional_aware(item.deleted_at),
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def conversation_record(item: models.Conversation) -> ConversationRecord:
    """把会话 ORM 实体复制为会话外安全记录。

    :param item: 当前事务中的会话实体。
    :return: 不依赖 ORM 会话的不可变记录。
    """

    return ConversationRecord(
        id=item.id,
        workspace_id=item.workspace_id,
        title=item.title,
        default_permission_mode=item.default_permission_mode,
        use_memory=item.use_memory,
        archived_at=_optional_aware(item.archived_at),
        deleted_at=_optional_aware(item.deleted_at),
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def run_record(item: models.Run) -> RunRecord:
    """把运行 ORM 实体复制为完整不可变投影。

    :param item: 当前事务中的运行实体。
    :return: 含状态、用量和时间的运行记录。
    """

    return RunRecord(
        id=item.id,
        workspace_id=item.workspace_id,
        conversation_id=item.conversation_id,
        client_request_id=item.client_request_id,
        permission_mode=item.permission_mode,
        use_memory=item.use_memory,
        status=item.status,
        model=item.model,
        reason=item.reason,
        error_code=item.error_code,
        error_message=item.error_message,
        prompt_tokens=item.prompt_tokens,
        completion_tokens=item.completion_tokens,
        total_tokens=item.total_tokens,
        prompt_cache_hit_tokens=item.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=item.prompt_cache_miss_tokens,
        model_calls=item.model_calls,
        tool_calls=item.tool_calls,
        duration_ms=item.duration_ms,
        cancel_requested_at=_optional_aware(item.cancel_requested_at),
        started_at=_optional_aware(item.started_at),
        finished_at=_optional_aware(item.finished_at),
        deleted_at=_optional_aware(item.deleted_at),
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def message_record(item: models.Message) -> MessageRecord:
    """把消息 ORM 实体复制为不可变记录。

    :param item: 当前事务中的消息实体。
    :return: 保留会话序号和正文的消息记录。
    """

    return MessageRecord(
        id=item.id,
        conversation_id=item.conversation_id,
        run_id=item.run_id,
        seq=item.seq,
        role=item.role,
        content=item.content,
        created_at=_aware(item.created_at),
        deleted_at=_optional_aware(item.deleted_at),
    )


def event_record(item: models.RunEvent) -> RunEventRecord:
    """把运行事件 ORM 实体复制为不可变记录。

    :param item: 当前事务中的安全运行事件。
    :return: 复制事件数据字典后的事件记录。
    """

    return RunEventRecord(
        run_id=item.run_id,
        seq=item.seq,
        event=item.event,
        data=dict(item.data),
        occurred_at=_aware(item.occurred_at),
    )


def approval_record(item: models.Approval) -> ApprovalRecord:
    """把审批 ORM 实体复制为不可变记录。

    :param item: 当前事务中的审批实体。
    :return: 复制安全请求数据后的审批记录。
    """

    return ApprovalRecord(
        id=item.id,
        run_id=item.run_id,
        status=item.status,
        tool_name=item.tool_name,
        action_summary=item.action_summary,
        reason=item.reason,
        request_data=dict(item.request_data),
        expires_at=_aware(item.expires_at),
        resolved_at=_optional_aware(item.resolved_at),
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def memory_record(item: models.MemoryEntry) -> MemoryEntryRecord:
    """把记忆 ORM 实体复制为不可变记录。

    :param item: 当前事务中的记忆实体。
    :return: 可供业务层安全使用的记忆记录。
    """

    return MemoryEntryRecord(
        id=item.id,
        workspace_id=item.workspace_id,
        kind=item.kind,
        content=item.content,
        content_hash=item.content_hash,
        source=item.source,
        source_run_id=item.source_run_id,
        pinned=item.pinned,
        enabled=item.enabled,
        confirmed_at=_aware(item.confirmed_at),
        deleted_at=_optional_aware(item.deleted_at),
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def run_memory_record(item: models.RunMemory) -> RunMemoryRecord:
    """把运行记忆 ORM 实体复制为不可变快照记录。

    :param item: 当前事务中的运行记忆实体。
    :return: 可用于重建上下文的冻结记忆记录。
    """

    return RunMemoryRecord(
        run_id=item.run_id,
        position=item.position,
        memory_entry_id=item.memory_entry_id,
        kind=item.kind,
        content=item.content,
        captured_at=_aware(item.captured_at),
    )


__all__ = [
    "ApprovalRecord",
    "ConversationRecord",
    "MemoryEntryRecord",
    "MessageRecord",
    "RunEventRecord",
    "RunMemoryRecord",
    "RunRecord",
    "WorkspaceRecord",
    "approval_record",
    "conversation_record",
    "event_record",
    "memory_record",
    "message_record",
    "run_memory_record",
    "run_record",
    "workspace_record",
]
