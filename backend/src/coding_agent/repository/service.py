"""供 FastAPI 和运行集成使用、负责会话生命周期的持久化门面。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from coding_agent.models import (
    ApprovalStatus,
    MemoryKind,
    MemorySource,
    Message,
    PermissionMode,
    RunStatus,
)
from .records import (
    ApprovalRecord,
    ConversationRecord,
    MemoryEntryRecord,
    MessageRecord,
    RunEventRecord,
    RunMemoryRecord,
    RunRecord,
    WorkspaceRecord,
    approval_record,
    conversation_record,
    event_record,
    memory_record,
    message_record,
    run_memory_record,
    run_record,
    workspace_record,
)
from .approval_repo import ApprovalRepository
from .base import (
    MAX_MEMORY_ENTRIES,
    UUIDLike,
    PersistenceConflictError,
    PersistenceNotFoundError,
)
from .conversation_repo import ConversationRepository
from .event_repo import RunEventRepository
from .memory_repo import MemoryRepository
from .message_repo import MessageRepository
from .run_repo import RunRepository
from .workspace_repo import WorkspaceRepository


@dataclass(frozen=True, slots=True)
class RunCreation:
    run: RunRecord
    user_message: MessageRecord
    prior_messages: tuple[MessageRecord, ...]
    memory_snapshot: tuple[RunMemoryRecord, ...]
    created: bool


class PersistenceService:
    """返回脱离会话的不可变记录，并负责所有事务边界。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_workspace(
        self, *, canonical_path: str, path_key: str, display_name: str
    ) -> WorkspaceRecord:
        with self.session_factory.begin() as session:
            repo = WorkspaceRepository(session)
            existing = repo.get_by_path_key(path_key)
            if existing is not None:
                raise PersistenceConflictError("workspace path is already registered")
            try:
                item = repo.create(
                    canonical_path=canonical_path,
                    path_key=path_key,
                    display_name=display_name,
                )
            except IntegrityError as exc:
                raise PersistenceConflictError("workspace path is already registered") from exc
            return workspace_record(item)

    def get_workspace(self, workspace_id: UUIDLike) -> WorkspaceRecord:
        with self.session_factory() as session:
            return workspace_record(WorkspaceRepository(session).require(workspace_id))

    def list_workspaces(self, *, include_archived: bool = False) -> list[WorkspaceRecord]:
        with self.session_factory() as session:
            return [
                workspace_record(item)
                for item in WorkspaceRepository(session).list(
                    include_archived=include_archived
                )
            ]

    def archive_workspace(
        self, workspace_id: UUIDLike, *, archived: bool = True
    ) -> WorkspaceRecord:
        with self.session_factory.begin() as session:
            WorkspaceRepository(session).require(workspace_id, for_update=True)
            if archived and RunRepository(session).active_for_workspace(workspace_id) is not None:
                raise PersistenceConflictError("workspace has an active run")
            return workspace_record(
                WorkspaceRepository(session).archive(workspace_id, archived=archived)
            )

    def delete_workspace(self, workspace_id: UUIDLike) -> WorkspaceRecord:
        with self.session_factory.begin() as session:
            WorkspaceRepository(session).require(workspace_id, for_update=True)
            if RunRepository(session).active_for_workspace(workspace_id) is not None:
                raise PersistenceConflictError("workspace has an active run")
            return workspace_record(WorkspaceRepository(session).soft_delete(workspace_id))

    def create_conversation(
        self,
        *,
        workspace_id: UUIDLike,
        title: str,
        default_permission_mode: PermissionMode | str = PermissionMode.AGENT,
        use_memory: bool = True,
    ) -> ConversationRecord:
        """在可用工作区内创建会话，并返回与 ORM 解耦的记录对象。"""

        with self.session_factory.begin() as session:
            # 第一步：锁定工作区并阻止在已归档工作区继续创建内容。
            workspace = WorkspaceRepository(session).require(
                workspace_id, for_update=True
            )
            if workspace.archived_at is not None:
                raise PersistenceConflictError("workspace is archived")
            # 第二步：在同一事务创建会话并转换为跨层使用的不可变记录。
            item = ConversationRepository(session).create(
                workspace_id=workspace.id,
                title=title,
                default_permission_mode=default_permission_mode,
                use_memory=use_memory,
            )
            return conversation_record(item)

    def get_conversation(
        self, conversation_id: UUIDLike, *, workspace_id: UUIDLike | None = None
    ) -> ConversationRecord:
        with self.session_factory() as session:
            return conversation_record(
                ConversationRepository(session).require(
                    conversation_id, workspace_id=workspace_id
                )
            )

    def list_conversations(
        self, workspace_id: UUIDLike, *, include_archived: bool = False
    ) -> list[ConversationRecord]:
        with self.session_factory() as session:
            return [
                conversation_record(item)
                for item in ConversationRepository(session).list(
                    workspace_id, include_archived=include_archived
                )
            ]

    def update_conversation(
        self,
        workspace_id: UUIDLike,
        conversation_id: UUIDLike,
        *,
        title: str | None = None,
        default_permission_mode: PermissionMode | str | None = None,
        use_memory: bool | None = None,
    ) -> ConversationRecord:
        """在工作区归属约束下部分更新会话。"""

        with self.session_factory.begin() as session:
            # 第一步：锁定父工作区，使工作区状态变化与会话修改串行化。
            WorkspaceRepository(session).require(workspace_id, for_update=True)
            # 第二步：限定同一工作区更新目标，并在事务内生成返回记录。
            return conversation_record(
                ConversationRepository(session).update(
                    conversation_id,
                    workspace_id=workspace_id,
                    title=title,
                    default_permission_mode=default_permission_mode,
                    use_memory=use_memory,
                )
            )

    def rename_conversation(
        self, workspace_id: UUIDLike, conversation_id: UUIDLike, *, title: str
    ) -> ConversationRecord:
        return self.update_conversation(
            workspace_id, conversation_id, title=title
        )

    def archive_conversation(
        self,
        workspace_id: UUIDLike,
        conversation_id: UUIDLike,
        *,
        archived: bool = True,
    ) -> ConversationRecord:
        with self.session_factory.begin() as session:
            WorkspaceRepository(session).require(workspace_id, for_update=True)
            return conversation_record(
                ConversationRepository(session).archive(
                    conversation_id, workspace_id=workspace_id, archived=archived
                )
            )

    def delete_conversation(
        self, workspace_id: UUIDLike, conversation_id: UUIDLike
    ) -> ConversationRecord:
        with self.session_factory.begin() as session:
            WorkspaceRepository(session).require(workspace_id, for_update=True)
            conversation = ConversationRepository(session).require(
                conversation_id, workspace_id=workspace_id, for_update=True
            )
            active = RunRepository(session).active_for_workspace(conversation.workspace_id)
            if active is not None and active.conversation_id == conversation.id:
                raise PersistenceConflictError("conversation has an active run")
            return conversation_record(
                ConversationRepository(session).soft_delete(
                    conversation_id, workspace_id=workspace_id
                )
            )

    def list_messages(
        self,
        conversation_id: UUIDLike,
        *,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[MessageRecord]:
        with self.session_factory() as session:
            ConversationRepository(session).require(conversation_id)
            return [
                message_record(item)
                for item in MessageRepository(session).list(
                    conversation_id, after_seq=after_seq, limit=limit
                )
            ]

    def history(
        self, conversation_id: UUIDLike, *, limit: int = 100
    ) -> list[MessageRecord]:
            # 表中只存在 USER/ASSISTANT 消息，因此不会把工具输出或隐藏模型状态
            # 泄露到未来提示词中。
        with self.session_factory() as session:
            ConversationRepository(session).require(conversation_id)
            return [
                message_record(item)
                for item in MessageRepository(session).history(
                    conversation_id, limit=limit
                )
            ]

    def create_run_with_user_message(
        self,
        *,
        conversation_id: UUIDLike,
        content: str,
        permission_mode: PermissionMode | str,
        use_memory: bool,
        client_request_id: str,
        model: str | None = None,
        run_id: UUIDLike | None = None,
    ) -> RunCreation:
        """在单个事务中创建运行、用户消息、历史和冻结的记忆快照。"""

        # 第一步：按“工作区→会话→运行”的全局顺序加锁，避免与记忆变更形成死锁。
        try:
            with self.session_factory.begin() as session:
                conversations = ConversationRepository(session)
                # 先读取不可变的工作区 ID，再依照全局顺序加锁；记忆变更也先锁工作区。
                candidate = conversations.require(conversation_id)
                workspace = WorkspaceRepository(session).require(
                    candidate.workspace_id, for_update=True
                )
                conversation = conversations.require(
                    conversation_id,
                    workspace_id=workspace.id,
                    for_update=True,
                )
                if conversation.archived_at is not None:
                    raise PersistenceConflictError("conversation is archived")
                if workspace.archived_at is not None:
                    raise PersistenceConflictError("workspace is archived")

                runs = RunRepository(session)
                # 第二步：幂等键已存在时返回原始运行及其创建时上下文，不启动新运行。
                existing = runs.get_by_request(conversation.id, client_request_id)
                if existing is not None:
                    message = self._user_message_for_run(session, existing.id)
                    if message is None:
                        raise PersistenceConflictError(
                            "idempotent run is missing its user message"
                        )
                    return RunCreation(
                        run=run_record(existing),
                        user_message=message_record(message),
                        prior_messages=tuple(
                            message_record(item)
                            for item in MessageRepository(session).history(
                                conversation.id,
                                limit=100,
                                before_seq=message.seq,
                            )
                        ),
                        memory_snapshot=tuple(
                            run_memory_record(item)
                            for item in MemoryRepository(session).list_snapshot(existing.id)
                        ),
                        created=False,
                    )
                # 第三步：确认工作区无活动运行，再创建运行并冻结此前历史与当前记忆。
                active = runs.active_for_workspace(workspace.id)
                if active is not None:
                    raise PersistenceConflictError("workspace already has an active run")
                run = runs.create(
                    workspace_id=workspace.id,
                    conversation_id=conversation.id,
                    client_request_id=client_request_id,
                    permission_mode=permission_mode,
                    use_memory=use_memory,
                    model=model,
                    run_id=run_id,
                )
                prior_messages = tuple(
                    message_record(item)
                    for item in MessageRepository(session).history(
                        conversation.id, limit=100
                    )
                )
                message = MessageRepository(session).append(
                    conversation_id=conversation.id,
                    run_id=run.id,
                    role="user",
                    content=content,
                )
                memory_snapshot = (
                    tuple(
                        run_memory_record(item)
                        for item in MemoryRepository(session).snapshot_for_run(
                            run_id=run.id,
                            workspace_id=workspace.id,
                        )
                    )
                    if use_memory
                    else ()
                )
                return RunCreation(
                    run=run_record(run),
                    user_message=message_record(message),
                    prior_messages=prior_messages,
                    memory_snapshot=memory_snapshot,
                    created=True,
                )
        except IntegrityError as exc:
            # 第四步：并发重试可能先赢得幂等唯一约束；用新事务读取赢家，
            # 其他完整性错误统一映射为工作区冲突。
            with self.session_factory() as session:
                existing = RunRepository(session).get_by_request(
                    conversation_id, client_request_id
                )
                if existing is not None:
                    message = self._user_message_for_run(session, existing.id)
                    if message is not None:
                        return RunCreation(
                            run=run_record(existing),
                            user_message=message_record(message),
                            prior_messages=tuple(
                                message_record(item)
                                for item in MessageRepository(session).history(
                                    existing.conversation_id,
                                    limit=100,
                                    before_seq=message.seq,
                                )
                            ),
                            memory_snapshot=tuple(
                                run_memory_record(item)
                                for item in MemoryRepository(session).list_snapshot(
                                    existing.id
                                )
                            ),
                            created=False,
                        )
            raise PersistenceConflictError("workspace already has an active run") from exc

    def get_run(self, run_id: UUIDLike) -> RunRecord:
        with self.session_factory() as session:
            return run_record(RunRepository(session).require(run_id))

    def active_run_for_workspace(
        self, workspace_id: UUIDLike
    ) -> RunRecord | None:
        with self.session_factory() as session:
            WorkspaceRepository(session).require(workspace_id)
            item = RunRepository(session).active_for_workspace(workspace_id)
            return None if item is None else run_record(item)

    def set_run_status(
        self,
        run_id: UUIDLike,
        status: RunStatus | str,
        **fields: Any,
    ) -> RunRecord:
        with self.session_factory.begin() as session:
            return run_record(
                RunRepository(session).set_status(run_id, status, **fields)
            )

    def request_cancel(self, run_id: UUIDLike) -> RunRecord:
        with self.session_factory.begin() as session:
            return run_record(RunRepository(session).request_cancel(run_id))

    def append_assistant_message_and_finish(
        self,
        run_id: UUIDLike,
        *,
        content: str | None,
        status: RunStatus | str,
        reason: str | None,
        model_calls: int,
        tool_calls: int,
        usage: Mapping[str, int],
        duration_ms: int | None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> tuple[RunRecord, MessageRecord | None]:
        """原子写入唯一助手消息和运行终态，支持完成回调安全重试。"""

        # 第一步：沿统一锁顺序锁定工作区、会话和运行，并复核归属关系。
        with self.session_factory.begin() as session:
            runs = RunRepository(session)
            candidate = runs.require(run_id)
            workspace = WorkspaceRepository(session).require(
                candidate.workspace_id, for_update=True
            )
            conversation = ConversationRepository(session).require(
                candidate.conversation_id,
                workspace_id=workspace.id,
                for_update=True,
            )
            run = runs.require(run_id, for_update=True)
            if run.conversation_id != conversation.id or run.workspace_id != workspace.id:
                raise PersistenceConflictError("run ownership invariant is invalid")
            # 第二步：仅在尚无助手消息时创建内容，使终态回调具备幂等性。
            message_value: MessageRecord | None = None
            if content is not None and content.strip():
                existing = session.scalar(
                    select(Message).where(
                        Message.run_id == run.id,
                        Message.role == "assistant",
                        Message.deleted_at.is_(None),
                    )
                )
                if existing is None:
                    created = MessageRepository(session).append(
                        conversation_id=run.conversation_id,
                        run_id=run.id,
                        role="assistant",
                        content=content,
                    )
                    message_value = message_record(created)
                else:
                    message_value = message_record(existing)
            # 第三步：在同一事务中提交状态、预算统计、耗时和脱敏错误信息。
            updated = runs.update_result(
                run.id,
                status=status,
                reason=reason,
                model_calls=model_calls,
                tool_calls=tool_calls,
                usage=usage,
                duration_ms=duration_ms,
                error_code=error_code,
                error_message=error_message,
            )
            return run_record(updated), message_value

    def append_safe_event(
        self,
        run_id: UUIDLike,
        *,
        seq: int,
        event: str,
        timestamp: datetime,
        data: Mapping[str, Any] | None,
    ) -> RunEventRecord:
        with self.session_factory.begin() as session:
            RunRepository(session).require(run_id)
            item = RunEventRepository(session).append_safe_event(
                run_id, seq=seq, event=event, timestamp=timestamp, data=data
            )
            return event_record(item)

    def list_events(
        self, run_id: UUIDLike, *, after_seq: int = 0, limit: int = 1_000
    ) -> list[RunEventRecord]:
        with self.session_factory() as session:
            RunRepository(session).require(run_id)
            return [
                event_record(item)
                for item in RunEventRepository(session).list_events(
                    run_id, after_seq=after_seq, limit=limit
                )
            ]

    def next_event_sequence(self, run_id: UUIDLike) -> int:
        with self.session_factory() as session:
            RunRepository(session).require(run_id)
            return RunEventRepository(session).next_sequence(run_id)

    def create_approval(
        self,
        *,
        approval_id: UUIDLike,
        run_id: UUIDLike,
        tool_name: str,
        action_summary: str,
        reason: str,
        expires_at: datetime,
    ) -> ApprovalRecord:
        """为运行创建幂等审批记录，并与同一运行的其他写入串行化。"""

        with self.session_factory.begin() as session:
            # 第一步：锁定所属运行，使回调重试与该运行的其他写入串行执行。
            run = RunRepository(session).require(run_id, for_update=True)
            approvals = ApprovalRepository(session)
            # 第二步：若相同审批已经落库则返回原记录，实现事件重放幂等。
            existing = approvals.get(approval_id, for_update=True)
            if existing is not None:
                if existing.run_id != run.id:
                    raise PersistenceConflictError(
                        "approval belongs to a different run"
                    )
                return approval_record(existing)
            # 第三步：不存在时才创建 pending 记录，并随上下文提交整个事务。
            return approval_record(
                approvals.create(
                    approval_id=approval_id,
                    run_id=run.id,
                    tool_name=tool_name,
                    action_summary=action_summary,
                    reason=reason,
                    expires_at=expires_at,
                )
            )

    def resolve_approval(
        self, approval_id: UUIDLike, *, status: ApprovalStatus | str
    ) -> ApprovalRecord:
        with self.session_factory.begin() as session:
            approvals = ApprovalRepository(session)
            existing = approvals.get(approval_id, for_update=True)
            if existing is None:
                raise PersistenceNotFoundError("approval was not found")
            expected = ApprovalStatus(status)
            if expected is ApprovalStatus.PENDING:
                raise ValueError("pending is not a resolution")
            if existing.status == expected.value:
                return approval_record(existing)
            if existing.status != ApprovalStatus.PENDING.value:
                raise PersistenceConflictError("approval is no longer pending")
            return approval_record(approvals.resolve(approval_id, status=expected))

    def create_memory(
        self,
        *,
        workspace_id: UUIDLike,
        kind: MemoryKind | str,
        content: str,
        source: MemorySource | str = MemorySource.MANUAL,
        source_run_id: UUIDLike | None = None,
        pinned: bool = False,
        enabled: bool = True,
    ) -> MemoryEntryRecord:
        """在工作区无活动运行时创建记忆，并校验可选来源运行。"""

        # 第一步：锁定工作区并排除活动运行，保证运行使用的记忆快照不会被并发修改。
        with self.session_factory.begin() as session:
            workspace = WorkspaceRepository(session).require(
                workspace_id, for_update=True
            )
            if RunRepository(session).active_for_workspace(workspace.id) is not None:
                raise PersistenceConflictError("workspace has an active run")
            # 第二步：运行结果型记忆必须来自同工作区内已经成功完成的运行。
            source_value = MemorySource(source)
            if source_value is MemorySource.RUN_RESULT and source_run_id is None:
                raise ValueError("run_result memory requires source_run_id")
            if source_run_id is not None:
                source_run = RunRepository(session).require(source_run_id)
                if source_run.workspace_id != workspace.id:
                    raise PersistenceConflictError(
                        "source run belongs to a different workspace"
                    )
                if source_run.status != RunStatus.COMPLETED.value:
                    raise PersistenceConflictError(
                        "only a completed run can become workspace memory"
                    )
            # 第三步：创建记录，并将内容去重约束转换为稳定的领域冲突错误。
            try:
                item = MemoryRepository(session).create(
                    workspace_id=workspace_id,
                    kind=kind,
                    content=content,
                    source=source_value,
                    source_run_id=source_run_id,
                    pinned=pinned,
                    enabled=enabled,
                )
            except IntegrityError as exc:
                raise PersistenceConflictError("memory entry already exists") from exc
            return memory_record(item)

    def list_memories(
        self,
        workspace_id: UUIDLike,
        *,
        enabled_only: bool = False,
        limit: int = 500,
    ) -> list[MemoryEntryRecord]:
        with self.session_factory() as session:
            WorkspaceRepository(session).require(workspace_id)
            return [
                memory_record(item)
                for item in MemoryRepository(session).list(
                    workspace_id, enabled_only=enabled_only, limit=limit
                )
            ]

    def update_memory(
        self, workspace_id: UUIDLike, memory_id: UUIDLike, **changes: Any
    ) -> MemoryEntryRecord:
        with self.session_factory.begin() as session:
            workspace = WorkspaceRepository(session).require(
                workspace_id, for_update=True
            )
            if RunRepository(session).active_for_workspace(workspace.id) is not None:
                raise PersistenceConflictError("workspace has an active run")
            try:
                item = MemoryRepository(session).update(
                    memory_id, workspace_id=workspace_id, **changes
                )
            except IntegrityError as exc:
                raise PersistenceConflictError("memory entry already exists") from exc
            return memory_record(item)

    def delete_memory(
        self, workspace_id: UUIDLike, memory_id: UUIDLike
    ) -> MemoryEntryRecord:
        with self.session_factory.begin() as session:
            workspace = WorkspaceRepository(session).require(
                workspace_id, for_update=True
            )
            if RunRepository(session).active_for_workspace(workspace.id) is not None:
                raise PersistenceConflictError("workspace has an active run")
            return memory_record(
                MemoryRepository(session).soft_delete(
                    memory_id, workspace_id=workspace_id
                )
            )

    def purge_memories(self, workspace_id: UUIDLike) -> int:
        with self.session_factory.begin() as session:
            workspace = WorkspaceRepository(session).require(
                workspace_id, for_update=True
            )
            if RunRepository(session).active_for_workspace(workspace.id) is not None:
                raise PersistenceConflictError("workspace has an active run")
            return MemoryRepository(session).purge_workspace(workspace_id)

    def snapshot_memories(
        self, *, run_id: UUIDLike, limit: int = MAX_MEMORY_ENTRIES
    ) -> list[RunMemoryRecord]:
        with self.session_factory.begin() as session:
            run = RunRepository(session).require(run_id)
            if run.status != RunStatus.STARTING.value:
                raise PersistenceConflictError(
                    "memory may only be snapshotted while a run is starting"
                )
            return [
                run_memory_record(item)
                for item in MemoryRepository(session).snapshot_for_run(
                    run_id=run.id, workspace_id=run.workspace_id, limit=limit
                )
            ]

    def list_run_memories(self, run_id: UUIDLike) -> list[RunMemoryRecord]:
        with self.session_factory() as session:
            RunRepository(session).require(run_id)
            return [
                run_memory_record(item)
                for item in MemoryRepository(session).list_snapshot(run_id)
            ]

    @staticmethod
    def _user_message_for_run(session: Session, run_id: UUID) -> Message | None:
        return session.scalar(
            select(Message).where(
                Message.run_id == run_id,
                Message.role == "user",
                Message.deleted_at.is_(None),
            )
        )


__all__ = [
    "PersistenceConflictError",
    "PersistenceNotFoundError",
    "PersistenceService",
    "RunCreation",
]
