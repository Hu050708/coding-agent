"""持久化事务之外返回的不可变记录值。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from coding_agent import models


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _optional_aware(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    """脱离 ORM 会话后可安全传递的工作区记录。"""

    id: UUID
    canonical_path: str
    path_key: str
    display_name: str
    archived_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    """脱离 ORM 会话后可安全传递的会话记录。"""

    id: UUID
    workspace_id: UUID
    title: str
    default_permission_mode: str
    use_memory: bool
    archived_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RunRecord:
    """包含完整状态和用量投影的运行记录。"""

    id: UUID
    workspace_id: UUID
    conversation_id: UUID
    client_request_id: str
    permission_mode: str
    use_memory: bool
    status: str
    model: str | None
    reason: str | None
    error_code: str | None
    error_message: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    model_calls: int
    tool_calls: int
    duration_ms: int | None
    cancel_requested_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """带会话序号的不可变消息记录。"""

    id: UUID
    conversation_id: UUID
    run_id: UUID | None
    seq: int
    role: str
    content: str
    created_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class RunEventRecord:
    """带运行序号的不可变事件记录。"""

    run_id: UUID
    seq: int
    event: str
    data: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """提供给应用层的不可变审批记录。"""

    id: UUID
    run_id: UUID
    status: str
    tool_name: str
    action_summary: str
    reason: str
    request_data: dict[str, Any]
    expires_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryEntryRecord:
    """提供给应用层的不可变记忆记录。"""

    id: UUID
    workspace_id: UUID
    kind: str
    content: str
    content_hash: str
    source: str
    source_run_id: UUID | None
    pinned: bool
    enabled: bool
    confirmed_at: datetime
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RunMemoryRecord:
    """提供给运行上下文的不可变记忆快照记录。"""

    run_id: UUID
    position: int
    memory_entry_id: UUID | None
    kind: str
    content: str
    captured_at: datetime


def workspace_record(item: models.Workspace) -> WorkspaceRecord:
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
    return RunEventRecord(
        run_id=item.run_id,
        seq=item.seq,
        event=item.event,
        data=dict(item.data),
        occurred_at=_aware(item.occurred_at),
    )


def approval_record(item: models.Approval) -> ApprovalRecord:
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
