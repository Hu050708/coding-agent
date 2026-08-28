"""管理 Coding Agent 持久化状态的事务级仓储。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from coding_agent.models import (
    ApprovalStatus,
    MemoryKind,
    MemorySource,
    MessageRole,
    PermissionMode,
    RunStatus,
)
from coding_agent.models import (
    Approval,
    Conversation,
    MemoryEntry,
    Message,
    Run,
    RunEvent,
    RunMemory,
    Workspace,
)
from .safe_events import safe_approval_data, sanitize_run_event


UUIDLike = UUID | str
MAX_MEMORY_ENTRIES = 32
MAX_MEMORY_CHARS = 32_000
MAX_MEMORY_CONTENT_CHARS = 2_000

_RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.STARTING: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.CANCELLING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.BUDGET_EXHAUSTED,
            RunStatus.INTERRUPTED,
        }
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.BUDGET_EXHAUSTED,
            RunStatus.INTERRUPTED,
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.CANCELLING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.BUDGET_EXHAUSTED,
            RunStatus.INTERRUPTED,
        }
    ),
    RunStatus.CANCELLING: frozenset(
        {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.BUDGET_EXHAUSTED,
            RunStatus.INTERRUPTED,
        }
    ),
}


class PersistenceNotFoundError(LookupError):
    """表示请求的持久化实体不存在或已被软删除。"""

    pass


class PersistenceConflictError(RuntimeError):
    """表示操作违反当前持久化状态或唯一性约束。"""

    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_uuid(value: UUIDLike, *, label: str = "id") -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _required_text(value: str, *, label: str, limit: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    result = value.strip()
    if limit is not None and len(result) > limit:
        raise ValueError(f"{label} exceeds {limit} characters")
    return result


def _validate_run_transition(current: RunStatus, target: RunStatus) -> None:
    if current is target:
        return
    if target not in _RUN_TRANSITIONS.get(current, frozenset()):
        raise PersistenceConflictError(
            f"run cannot transition from {current.value} to {target.value}"
        )


class WorkspaceRepository:
    """封装工作区表的创建、查询、锁定和归档操作。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, *, canonical_path: str, path_key: str, display_name: str
    ) -> Workspace:
        item = Workspace(
            canonical_path=_required_text(canonical_path, label="canonical_path"),
            path_key=_required_text(path_key, label="path_key", limit=2048),
            display_name=_required_text(display_name, label="display_name", limit=255),
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get(
        self,
        workspace_id: UUIDLike,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Workspace | None:
        statement = select(Workspace).where(Workspace.id == as_uuid(workspace_id))
        if not include_deleted:
            statement = statement.where(Workspace.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def require(self, workspace_id: UUIDLike, *, for_update: bool = False) -> Workspace:
        item = self.get(workspace_id, for_update=for_update)
        if item is None:
            raise PersistenceNotFoundError("workspace was not found")
        return item

    def get_by_path_key(self, path_key: str) -> Workspace | None:
        return self.session.scalar(
            select(Workspace).where(
                Workspace.path_key == _required_text(path_key, label="path_key", limit=2048),
                Workspace.deleted_at.is_(None),
            )
        )

    def list(self, *, include_archived: bool = False) -> list[Workspace]:
        statement = select(Workspace).where(Workspace.deleted_at.is_(None))
        if not include_archived:
            statement = statement.where(Workspace.archived_at.is_(None))
        statement = statement.order_by(Workspace.updated_at.desc(), Workspace.display_name)
        return list(self.session.scalars(statement))

    def archive(self, workspace_id: UUIDLike, *, archived: bool = True) -> Workspace:
        item = self.require(workspace_id, for_update=True)
        item.archived_at = utc_now() if archived else None
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def soft_delete(self, workspace_id: UUIDLike) -> Workspace:
        item = self.require(workspace_id, for_update=True)
        now = utc_now()
        item.deleted_at = now
        item.archived_at = item.archived_at or now
        item.updated_at = now
        self.session.flush()
        return item


class ConversationRepository:
    """封装会话表及其工作区归属约束。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        workspace_id: UUIDLike,
        title: str,
        default_permission_mode: PermissionMode | str = PermissionMode.AGENT,
        use_memory: bool = True,
    ) -> Conversation:
        mode = PermissionMode(default_permission_mode).value
        item = Conversation(
            workspace_id=as_uuid(workspace_id, label="workspace_id"),
            title=_required_text(title, label="title", limit=255),
            default_permission_mode=mode,
            use_memory=bool(use_memory),
            next_message_seq=1,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get(
        self,
        conversation_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Conversation | None:
        statement = select(Conversation).where(Conversation.id == as_uuid(conversation_id))
        if workspace_id is not None:
            statement = statement.where(
                Conversation.workspace_id == as_uuid(workspace_id, label="workspace_id")
            )
        if not include_deleted:
            statement = statement.where(Conversation.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def require(
        self,
        conversation_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        for_update: bool = False,
    ) -> Conversation:
        item = self.get(
            conversation_id, workspace_id=workspace_id, for_update=for_update
        )
        if item is None:
            raise PersistenceNotFoundError("conversation was not found")
        return item

    def list(
        self, workspace_id: UUIDLike, *, include_archived: bool = False
    ) -> list[Conversation]:
        statement = select(Conversation).where(
            Conversation.workspace_id == as_uuid(workspace_id, label="workspace_id"),
            Conversation.deleted_at.is_(None),
        )
        if not include_archived:
            statement = statement.where(Conversation.archived_at.is_(None))
        statement = statement.order_by(
            Conversation.updated_at.desc(), Conversation.created_at.desc()
        )
        return list(self.session.scalars(statement))

    def rename(self, conversation_id: UUIDLike, *, title: str) -> Conversation:
        return self.update(conversation_id, title=title)

    def update(
        self,
        conversation_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        title: str | None = None,
        default_permission_mode: PermissionMode | str | None = None,
        use_memory: bool | None = None,
    ) -> Conversation:
        if title is None and default_permission_mode is None and use_memory is None:
            raise ValueError("at least one conversation field must be updated")
        item = self.require(
            conversation_id, workspace_id=workspace_id, for_update=True
        )
        if title is not None:
            item.title = _required_text(title, label="title", limit=255)
        if default_permission_mode is not None:
            item.default_permission_mode = PermissionMode(default_permission_mode).value
        if use_memory is not None:
            item.use_memory = bool(use_memory)
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def archive(
        self,
        conversation_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        archived: bool = True,
    ) -> Conversation:
        item = self.require(
            conversation_id, workspace_id=workspace_id, for_update=True
        )
        item.archived_at = utc_now() if archived else None
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def soft_delete(
        self, conversation_id: UUIDLike, *, workspace_id: UUIDLike | None = None
    ) -> Conversation:
        item = self.require(
            conversation_id, workspace_id=workspace_id, for_update=True
        )
        now = utc_now()
        item.deleted_at = now
        item.archived_at = item.archived_at or now
        item.updated_at = now
        self.session.flush()
        return item


class RunRepository:
    """封装运行状态机、活动运行查询和终态结果写入。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        workspace_id: UUIDLike,
        conversation_id: UUIDLike,
        client_request_id: str,
        permission_mode: PermissionMode | str,
        use_memory: bool,
        model: str | None = None,
        run_id: UUIDLike | None = None,
    ) -> Run:
        item = Run(
            workspace_id=as_uuid(workspace_id, label="workspace_id"),
            conversation_id=as_uuid(conversation_id, label="conversation_id"),
            client_request_id=_required_text(
                client_request_id, label="client_request_id", limit=128
            ),
            permission_mode=PermissionMode(permission_mode).value,
            use_memory=bool(use_memory),
            status=RunStatus.STARTING.value,
            model=(None if model is None else _required_text(model, label="model", limit=255)),
        )
        if run_id is not None:
            item.id = as_uuid(run_id, label="run_id")
        self.session.add(item)
        self.session.flush()
        return item

    def get(
        self, run_id: UUIDLike, *, include_deleted: bool = False, for_update: bool = False
    ) -> Run | None:
        statement = select(Run).where(Run.id == as_uuid(run_id, label="run_id"))
        if not include_deleted:
            statement = statement.where(Run.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def require(self, run_id: UUIDLike, *, for_update: bool = False) -> Run:
        item = self.get(run_id, for_update=for_update)
        if item is None:
            raise PersistenceNotFoundError("run was not found")
        return item

    def get_by_request(
        self, conversation_id: UUIDLike, client_request_id: str
    ) -> Run | None:
        return self.session.scalar(
            select(Run).where(
                Run.conversation_id == as_uuid(conversation_id, label="conversation_id"),
                Run.client_request_id
                == _required_text(client_request_id, label="client_request_id", limit=128),
            )
        )

    def active_for_workspace(self, workspace_id: UUIDLike) -> Run | None:
        return self.session.scalar(
            select(Run).where(
                Run.workspace_id == as_uuid(workspace_id, label="workspace_id"),
                Run.status.in_(
                    [
                        RunStatus.STARTING.value,
                        RunStatus.RUNNING.value,
                        RunStatus.WAITING_APPROVAL.value,
                        RunStatus.CANCELLING.value,
                    ]
                ),
                Run.deleted_at.is_(None),
            )
        )

    def set_status(
        self,
        run_id: UUIDLike,
        status: RunStatus | str,
        *,
        reason: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> Run:
        item = self.require(run_id, for_update=True)
        value = RunStatus(status)
        _validate_run_transition(RunStatus(item.status), value)
        item.status = value.value
        item.reason = reason[:128] if reason else None
        item.error_code = error_code[:128] if error_code else None
        item.error_message = error_message[:2000] if error_message else None
        if started_at is not None:
            item.started_at = started_at
        if finished_at is not None:
            item.finished_at = finished_at
        elif value not in {
            RunStatus.STARTING,
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
        }:
            item.finished_at = utc_now()
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def update_result(
        self,
        run_id: UUIDLike,
        *,
        status: RunStatus | str,
        reason: str | None,
        model_calls: int,
        tool_calls: int,
        usage: Mapping[str, int],
        duration_ms: int | None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Run:
        """校验终态转换和计数器后，将完整运行结果写入锁定记录。"""

        # 第一步：锁定运行并确认目标状态是合法终态转换。
        item = self.require(run_id, for_update=True)
        value = RunStatus(status)
        if value in {
            RunStatus.STARTING,
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
        }:
            raise ValueError("run result status must be terminal")
        _validate_run_transition(RunStatus(item.status), value)
        # 第二步：统一校验所有用量计数和耗时均为非负整数。
        counters = {
            "model_calls": model_calls,
            "tool_calls": tool_calls,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "prompt_cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
            "prompt_cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0),
        }
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counters.values()
        ):
            raise ValueError("run result counters must be non-negative integers")
        if duration_ms is not None and (
            isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0
        ):
            raise ValueError("duration_ms must be a non-negative integer")
        # 第三步：截断公开原因和错误文本，设置完成时间后刷新事务。
        for name, counter in counters.items():
            setattr(item, name, counter)
        item.duration_ms = duration_ms
        item.status = value.value
        item.reason = reason[:128] if reason else None
        item.error_code = error_code[:128] if error_code else None
        item.error_message = error_message[:2000] if error_message else None
        item.finished_at = utc_now()
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def request_cancel(self, run_id: UUIDLike) -> Run:
        item = self.require(run_id, for_update=True)
        current = RunStatus(item.status)
        if current not in {
            RunStatus.STARTING,
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
        }:
            raise PersistenceConflictError("run is already terminal")
        if current is not RunStatus.CANCELLING:
            item.status = RunStatus.CANCELLING.value
        if item.cancel_requested_at is None:
            item.cancel_requested_at = utc_now()
        item.updated_at = utc_now()
        self.session.flush()
        return item


class MessageRepository:
    """维护会话内严格递增的消息序号和消息历史。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self,
        *,
        conversation_id: UUIDLike,
        role: MessageRole | str,
        content: str,
        run_id: UUIDLike | None = None,
    ) -> Message:
        conversation = self.session.scalar(
            select(Conversation)
            .where(
                Conversation.id == as_uuid(conversation_id, label="conversation_id"),
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if conversation is None:
            raise PersistenceNotFoundError("conversation was not found")
        seq = conversation.next_message_seq
        conversation.next_message_seq += 1
        conversation.updated_at = utc_now()
        item = Message(
            conversation_id=conversation.id,
            run_id=None if run_id is None else as_uuid(run_id, label="run_id"),
            seq=seq,
            role=MessageRole(role).value,
            content=_required_text(content, label="content"),
        )
        self.session.add(item)
        self.session.flush()
        return item

    def list(
        self,
        conversation_id: UUIDLike,
        *,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[Message]:
        if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
            raise ValueError("after_seq must be a non-negative integer")
        safe_limit = max(1, min(int(limit), 2_000))
        statement = (
            select(Message)
            .where(
                Message.conversation_id == as_uuid(conversation_id, label="conversation_id"),
                Message.deleted_at.is_(None),
                Message.seq > after_seq,
            )
            .order_by(Message.seq)
            .limit(safe_limit)
        )
        return list(self.session.scalars(statement))

    def history(
        self,
        conversation_id: UUIDLike,
        *,
        limit: int = 100,
        before_seq: int | None = None,
    ) -> list[Message]:
        safe_limit = max(1, min(int(limit), 500))
        conditions = [
            Message.conversation_id
            == as_uuid(conversation_id, label="conversation_id"),
            Message.deleted_at.is_(None),
        ]
        if before_seq is not None:
            if (
                isinstance(before_seq, bool)
                or not isinstance(before_seq, int)
                or before_seq < 1
            ):
                raise ValueError("before_seq must be a positive integer")
            conditions.append(Message.seq < before_seq)
        newest_first = list(
            self.session.scalars(
                select(Message)
                .where(*conditions)
                .order_by(Message.seq.desc())
                .limit(safe_limit)
            )
        )
        return list(reversed(newest_first))

    def soft_delete_conversation(self, conversation_id: UUIDLike) -> int:
        now = utc_now()
        items = self.list(conversation_id, after_seq=0, limit=2_000)
        for item in items:
            item.deleted_at = now
        self.session.flush()
        return len(items)


class RunEventRepository:
    """按运行内序号持久化和分页读取可重放事件。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def append_safe_event(
        self,
        run_id: UUIDLike,
        *,
        seq: int,
        event: str,
        timestamp: datetime,
        data: Mapping[str, Any] | None,
    ) -> RunEvent:
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise ValueError("seq must be a positive integer")
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        safe_data = sanitize_run_event(event, data)
        item = RunEvent(
            run_id=as_uuid(run_id, label="run_id"),
            seq=seq,
            event=event,
            occurred_at=timestamp,
            data=safe_data,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def list_events(
        self, run_id: UUIDLike, *, after_seq: int = 0, limit: int = 1_000
    ) -> list[RunEvent]:
        if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
            raise ValueError("after_seq must be a non-negative integer")
        safe_limit = max(1, min(int(limit), 5_000))
        statement = (
            select(RunEvent)
            .where(
                RunEvent.run_id == as_uuid(run_id, label="run_id"),
                RunEvent.seq > after_seq,
            )
            .order_by(RunEvent.seq)
            .limit(safe_limit)
        )
        return list(self.session.scalars(statement))

    def next_sequence(self, run_id: UUIDLike) -> int:
        maximum = self.session.scalar(
            select(func.max(RunEvent.seq)).where(
                RunEvent.run_id == as_uuid(run_id, label="run_id")
            )
        )
        return int(maximum or 0) + 1


class ApprovalRepository:
    """管理工具审批的创建、锁定和一次性状态转换。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        approval_id: UUIDLike,
        run_id: UUIDLike,
        tool_name: str,
        action_summary: str,
        reason: str,
        expires_at: datetime,
    ) -> Approval:
        if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        safe = safe_approval_data(
            tool_name=tool_name, action_summary=action_summary, reason=reason
        )
        item = Approval(
            id=as_uuid(approval_id, label="approval_id"),
            run_id=as_uuid(run_id, label="run_id"),
            status=ApprovalStatus.PENDING.value,
            tool_name=safe["tool_name"],
            action_summary=safe["action_summary"],
            reason=safe["reason"],
            request_data=dict(safe),
            expires_at=expires_at,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get(self, approval_id: UUIDLike, *, for_update: bool = False) -> Approval | None:
        statement = select(Approval).where(
            Approval.id == as_uuid(approval_id, label="approval_id")
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def pending_for_run(self, run_id: UUIDLike) -> Approval | None:
        return self.session.scalar(
            select(Approval).where(
                Approval.run_id == as_uuid(run_id, label="run_id"),
                Approval.status == ApprovalStatus.PENDING.value,
            )
        )

    def resolve(
        self, approval_id: UUIDLike, *, status: ApprovalStatus | str
    ) -> Approval:
        item = self.get(approval_id, for_update=True)
        if item is None:
            raise PersistenceNotFoundError("approval was not found")
        if item.status != ApprovalStatus.PENDING.value:
            raise PersistenceConflictError("approval is no longer pending")
        value = ApprovalStatus(status)
        if value is ApprovalStatus.PENDING:
            raise ValueError("pending is not a resolution")
        item.status = value.value
        item.resolved_at = utc_now()
        item.updated_at = item.resolved_at
        self.session.flush()
        return item


class MemoryRepository:
    """管理工作区记忆以及绑定到运行的不可变快照。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def content_hash(content: str) -> str:
        normalized = _required_text(content, label="content")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def create(
        self,
        *,
        workspace_id: UUIDLike,
        kind: MemoryKind | str,
        content: str,
        source: MemorySource | str = MemorySource.MANUAL,
        source_run_id: UUIDLike | None = None,
        pinned: bool = False,
        enabled: bool = True,
    ) -> MemoryEntry:
        clean_content = _required_text(
            content, label="content", limit=MAX_MEMORY_CONTENT_CHARS
        )
        item = MemoryEntry(
            workspace_id=as_uuid(workspace_id, label="workspace_id"),
            kind=MemoryKind(kind).value,
            content=clean_content,
            content_hash=self.content_hash(clean_content),
            source=MemorySource(source).value,
            source_run_id=(
                None if source_run_id is None else as_uuid(source_run_id, label="source_run_id")
            ),
            pinned=bool(pinned),
            enabled=bool(enabled),
            confirmed_at=utc_now(),
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get(
        self,
        memory_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> MemoryEntry | None:
        statement = select(MemoryEntry).where(
            MemoryEntry.id == as_uuid(memory_id, label="memory_id")
        )
        if workspace_id is not None:
            statement = statement.where(
                MemoryEntry.workspace_id == as_uuid(workspace_id, label="workspace_id")
            )
        if not include_deleted:
            statement = statement.where(MemoryEntry.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list(
        self,
        workspace_id: UUIDLike,
        *,
        enabled_only: bool = False,
        limit: int = 500,
    ) -> list[MemoryEntry]:
        statement = select(MemoryEntry).where(
            MemoryEntry.workspace_id == as_uuid(workspace_id, label="workspace_id"),
            MemoryEntry.deleted_at.is_(None),
        )
        if enabled_only:
            statement = statement.where(MemoryEntry.enabled.is_(True))
        statement = statement.order_by(
            MemoryEntry.pinned.desc(), MemoryEntry.updated_at.desc(), MemoryEntry.created_at.desc()
        ).limit(max(1, min(int(limit), 2_000)))
        return list(self.session.scalars(statement))

    def update(
        self,
        memory_id: UUIDLike,
        *,
        workspace_id: UUIDLike,
        kind: MemoryKind | str | None = None,
        content: str | None = None,
        pinned: bool | None = None,
        enabled: bool | None = None,
    ) -> MemoryEntry:
        item = self.get(memory_id, workspace_id=workspace_id, for_update=True)
        if item is None:
            raise PersistenceNotFoundError("memory entry was not found")
        if kind is not None:
            item.kind = MemoryKind(kind).value
        if content is not None:
            item.content = _required_text(
                content, label="content", limit=MAX_MEMORY_CONTENT_CHARS
            )
            item.content_hash = self.content_hash(item.content)
        if pinned is not None:
            item.pinned = bool(pinned)
        if enabled is not None:
            item.enabled = bool(enabled)
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def soft_delete(
        self, memory_id: UUIDLike, *, workspace_id: UUIDLike
    ) -> MemoryEntry:
        item = self.get(memory_id, workspace_id=workspace_id, for_update=True)
        if item is None:
            raise PersistenceNotFoundError("memory entry was not found")
        item.deleted_at = utc_now()
        item.enabled = False
        item.updated_at = item.deleted_at
        self.session.flush()
        return item

    def purge_workspace(self, workspace_id: UUIDLike) -> int:
        result = self.session.execute(
            delete(MemoryEntry).where(
                MemoryEntry.workspace_id == as_uuid(workspace_id, label="workspace_id")
            )
        )
        self.session.flush()
        return int(result.rowcount or 0)

    def snapshot_for_run(
        self,
        *,
        run_id: UUIDLike,
        workspace_id: UUIDLike,
        limit: int = MAX_MEMORY_ENTRIES,
        max_content_chars: int = MAX_MEMORY_CHARS,
    ) -> list[RunMemory]:
        """为运行创建一次不可变、有字符预算且顺序稳定的记忆快照。"""

        # 第一步：拒绝重复快照，并规范化条目数和字符数上限。
        run_uuid = as_uuid(run_id, label="run_id")
        existing = self.session.scalar(
            select(func.count()).select_from(RunMemory).where(RunMemory.run_id == run_uuid)
        )
        if existing:
            raise PersistenceConflictError("run memory snapshot is immutable")
        safe_limit = max(1, min(int(limit), MAX_MEMORY_ENTRIES))
        if (
            isinstance(max_content_chars, bool)
            or not isinstance(max_content_chars, int)
            or max_content_chars < 1
        ):
            raise ValueError("max_content_chars must be a positive integer")
        # 第二步：按仓储既定顺序选取完整前缀，字符预算触顶即停止。
        candidates = self.list(
            workspace_id, enabled_only=True, limit=safe_limit
        )
        entries: list[MemoryEntry] = []
        used_chars = 0
        for entry in candidates:
            content_chars = len(entry.content)
            if used_chars + content_chars > max_content_chars:
                break
            entries.append(entry)
            used_chars += content_chars
        # 第三步：保存位置序号和内容副本，使后续原记忆变更不影响本次运行。
        snapshots = [
            RunMemory(
                run_id=run_uuid,
                position=position,
                memory_entry_id=entry.id,
                kind=entry.kind,
                content=entry.content,
            )
            for position, entry in enumerate(entries, start=1)
        ]
        self.session.add_all(snapshots)
        self.session.flush()
        return snapshots

    def list_snapshot(self, run_id: UUIDLike) -> list[RunMemory]:
        return list(
            self.session.scalars(
                select(RunMemory)
                .where(RunMemory.run_id == as_uuid(run_id, label="run_id"))
                .order_by(RunMemory.position)
            )
        )


__all__ = [
    "ApprovalRepository",
    "ConversationRepository",
    "MemoryRepository",
    "MAX_MEMORY_CHARS",
    "MAX_MEMORY_CONTENT_CHARS",
    "MAX_MEMORY_ENTRIES",
    "MessageRepository",
    "PersistenceConflictError",
    "PersistenceNotFoundError",
    "RunEventRepository",
    "RunRepository",
    "UUIDLike",
    "WorkspaceRepository",
    "as_uuid",
    "utc_now",
]
