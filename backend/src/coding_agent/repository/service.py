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
    """创建运行事务返回的完整、不可变上下文。"""

    # 新建或由幂等键命中的运行记录。
    run: RunRecord
    # 与该运行绑定的当前用户消息。
    user_message: MessageRecord
    # 当前用户消息之前的会话历史。
    prior_messages: tuple[MessageRecord, ...]
    # 在创建运行时冻结的项目记忆。
    memory_snapshot: tuple[RunMemoryRecord, ...]
    # True 表示本次真正创建；False 表示返回已有幂等结果。
    created: bool


class PersistenceService:
    """返回脱离会话的不可变记录，并负责所有事务边界。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """初始化持久化门面。

        :param session_factory: 为每次方法调用创建独立事务会话的工厂。
        """

        # 只保存会话工厂，绝不跨请求复用 ORM Session。
        self.session_factory = session_factory

    def create_workspace(
        self, *, canonical_path: str, path_key: str, display_name: str
    ) -> WorkspaceRecord:
        """登记唯一的规范工作区路径。

        :param canonical_path: 已经安全策略验证的绝对路径。
        :param path_key: 用于唯一比较的规范路径键。
        :param display_name: 用户可见工作区名称。
        :return: 新工作区的不可变记录。
        :raises PersistenceConflictError: 路径已被登记。
        """

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
        """读取一个活动工作区。

        :param workspace_id: 工作区 ID。
        :return: 工作区不可变记录。
        :raises PersistenceNotFoundError: 工作区不存在或已删除。
        """

        with self.session_factory() as session:
            return workspace_record(WorkspaceRepository(session).require(workspace_id))

    def list_workspaces(self, *, include_archived: bool = False) -> list[WorkspaceRecord]:
        """列出工作区目录。

        :param include_archived: 是否包含已归档工作区。
        :return: 与 ORM 会话解耦的工作区记录列表。
        """

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
        """归档或恢复工作区。

        :param workspace_id: 目标工作区 ID。
        :param archived: True 归档，False 恢复。
        :return: 更新后的工作区记录。
        :raises PersistenceConflictError: 归档时工作区仍有活动运行。
        """

        with self.session_factory.begin() as session:
            WorkspaceRepository(session).require(workspace_id, for_update=True)
            if archived and RunRepository(session).active_for_workspace(workspace_id) is not None:
                raise PersistenceConflictError("workspace has an active run")
            return workspace_record(
                WorkspaceRepository(session).archive(workspace_id, archived=archived)
            )

    def delete_workspace(self, workspace_id: UUIDLike) -> WorkspaceRecord:
        """软删除没有活动运行的工作区。

        :param workspace_id: 目标工作区 ID。
        :return: 删除后的工作区记录。
        :raises PersistenceConflictError: 工作区仍有活动运行。
        """

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
        """在可用工作区内创建会话，并返回与 ORM 解耦的记录对象。

        :param workspace_id: 会话所属工作区 ID。
        :param title: 非空会话标题。
        :param default_permission_mode: 新运行默认权限模式。
        :param use_memory: 新运行默认是否使用记忆。
        :return: 新会话不可变记录。
        :raises PersistenceConflictError: 工作区已经归档。
        """

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
        """读取活动会话并可验证其工作区归属。

        :param conversation_id: 会话 ID。
        :param workspace_id: 可选所属工作区 ID 限制。
        :return: 会话不可变记录。
        """

        with self.session_factory() as session:
            return conversation_record(
                ConversationRepository(session).require(
                    conversation_id, workspace_id=workspace_id
                )
            )

    def list_conversations(
        self, workspace_id: UUIDLike, *, include_archived: bool = False
    ) -> list[ConversationRecord]:
        """列出工作区中的会话。

        :param workspace_id: 工作区 ID。
        :param include_archived: 是否包含已归档会话。
        :return: 会话不可变记录列表。
        """

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
        """在工作区归属约束下部分更新会话。

        :param workspace_id: 所属工作区 ID。
        :param conversation_id: 目标会话 ID。
        :param title: 新标题；None 表示不修改。
        :param default_permission_mode: 新默认权限；None 表示不修改。
        :param use_memory: 新默认记忆开关；None 表示不修改。
        :return: 更新后的会话记录。
        """

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
        """仅修改会话标题。

        :param workspace_id: 所属工作区 ID。
        :param conversation_id: 目标会话 ID。
        :param title: 新的非空标题。
        :return: 更新后的会话记录。
        """

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
        """归档或恢复指定工作区中的会话。

        :param workspace_id: 所属工作区 ID。
        :param conversation_id: 目标会话 ID。
        :param archived: True 归档，False 恢复。
        :return: 更新后的会话记录。
        """

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
        """软删除没有活动运行的会话。

        :param workspace_id: 所属工作区 ID。
        :param conversation_id: 目标会话 ID。
        :return: 删除后的会话记录。
        :raises PersistenceConflictError: 会话当前仍有活动运行。
        """

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
        """分页列出会话消息。

        :param conversation_id: 会话 ID。
        :param after_seq: 仅返回序号严格大于该值的消息。
        :param limit: 本页最大消息数。
        :return: 按序号升序排列的消息记录。
        """

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
        """读取提供给 Agent 的最近可见会话历史。

        :param conversation_id: 会话 ID。
        :param limit: 最多返回的最近消息数。
        :return: 从旧到新排列且仅含用户、助手角色的消息记录。
        """

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
        """在单个事务中创建运行、用户消息、历史和冻结的记忆快照。

        :param conversation_id: 本次运行所属会话 ID。
        :param content: 当前用户任务正文。
        :param permission_mode: 本次运行采用的权限模式。
        :param use_memory: 是否冻结并使用项目记忆。
        :param client_request_id: 会话内唯一的客户端幂等请求标识。
        :param model: 可选实际模型名称。
        :param run_id: 可选预分配运行 ID。
        :return: 运行、当前消息、先前历史、记忆快照及是否新建的组合记录。
        :raises PersistenceConflictError: 资源已归档、工作区忙或幂等数据不完整。
        """

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
        """读取一个活动运行的持久化投影。

        :param run_id: 运行 ID。
        :return: 完整运行记录。
        """

        with self.session_factory() as session:
            return run_record(RunRepository(session).require(run_id))

    def active_run_for_workspace(
        self, workspace_id: UUIDLike
    ) -> RunRecord | None:
        """查询工作区当前活动运行。

        :param workspace_id: 工作区 ID。
        :return: 活动运行记录；没有时为 None。
        """

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
        """按运行状态机更新状态及附加字段。

        :param run_id: 目标运行 ID。
        :param status: 目标状态。
        :param fields: 传给仓储的原因、错误和时间等可选字段。
        :return: 更新后的运行记录。
        """

        with self.session_factory.begin() as session:
            return run_record(
                RunRepository(session).set_status(run_id, status, **fields)
            )

    def request_cancel(self, run_id: UUIDLike) -> RunRecord:
        """将活动运行标为取消中。

        :param run_id: 目标运行 ID。
        :return: 更新后的运行记录。
        """

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
        """原子写入唯一助手消息和运行终态，支持完成回调安全重试。

        :param run_id: 目标运行 ID。
        :param content: 可选最终助手正文；为空时不创建消息。
        :param status: 运行最终状态。
        :param reason: 可选终止原因。
        :param model_calls: 模型调用次数。
        :param tool_calls: 工具调用次数。
        :param usage: token 用量计数映射。
        :param duration_ms: 总耗时（毫秒）。
        :param error_code: 可选失败错误码。
        :param error_message: 可选安全失败说明。
        :return: 最新运行记录和可选的助手消息记录。
        """

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
        """清洗并持久化一条可重放运行事件。

        :param run_id: 事件所属运行 ID。
        :param seq: 运行内事件序号。
        :param event: 稳定事件类型。
        :param timestamp: 带时区发生时间。
        :param data: 待白名单化的事件数据。
        :return: 持久化后的不可变事件记录。
        """

        with self.session_factory.begin() as session:
            RunRepository(session).require(run_id)
            item = RunEventRepository(session).append_safe_event(
                run_id, seq=seq, event=event, timestamp=timestamp, data=data
            )
            return event_record(item)

    def list_events(
        self, run_id: UUIDLike, *, after_seq: int = 0, limit: int = 1_000
    ) -> list[RunEventRecord]:
        """分页列出持久化运行事件。

        :param run_id: 运行 ID。
        :param after_seq: 断点续传游标，仅返回更大序号。
        :param limit: 本页最大事件数。
        :return: 按序号升序排列的事件记录。
        """

        with self.session_factory() as session:
            RunRepository(session).require(run_id)
            return [
                event_record(item)
                for item in RunEventRepository(session).list_events(
                    run_id, after_seq=after_seq, limit=limit
                )
            ]

    def next_event_sequence(self, run_id: UUIDLike) -> int:
        """计算持久化事件的下一序号。

        :param run_id: 运行 ID。
        :return: 当前最大事件序号加一。
        """

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
        """为运行创建幂等审批记录，并与同一运行的其他写入串行化。

        :param approval_id: 运行时生成的审批 ID。
        :param run_id: 所属运行 ID。
        :param tool_name: 待审批工具名称。
        :param action_summary: 面向用户的操作摘要。
        :param reason: 需要审批的原因。
        :param expires_at: 带时区自动过期时间。
        :return: 新建或幂等命中的审批记录。
        :raises PersistenceConflictError: 相同审批 ID 属于其他运行。
        """

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
        """幂等地终结一条审批记录。

        :param approval_id: 审批 ID。
        :param status: 非 pending 的目标状态。
        :return: 已存在或本次更新后的审批记录。
        :raises PersistenceNotFoundError: 审批不存在。
        :raises PersistenceConflictError: 审批已以其他状态处理。
        """

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
        """在工作区无活动运行时创建记忆，并校验可选来源运行。

        :param workspace_id: 记忆所属工作区 ID。
        :param kind: 记忆业务分类。
        :param content: 非空记忆正文。
        :param source: 人工或运行结果来源。
        :param source_run_id: 可选的已完成来源运行 ID。
        :param pinned: 是否置顶。
        :param enabled: 是否允许用于上下文。
        :return: 创建后的记忆记录。
        :raises PersistenceConflictError: 工作区忙、来源运行无效或正文重复。
        """

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
        """列出工作区记忆。

        :param workspace_id: 工作区 ID。
        :param enabled_only: 是否只返回启用条目。
        :param limit: 最大返回条目数。
        :return: 按优先级排序的记忆记录。
        """

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
        """在工作区空闲时部分更新记忆。

        :param workspace_id: 所属工作区 ID。
        :param memory_id: 目标记忆 ID。
        :param changes: 分类、正文、置顶或启用状态等实际变更。
        :return: 更新后的记忆记录。
        :raises PersistenceConflictError: 工作区忙或新正文重复。
        """

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
        """在工作区空闲时软删除一条记忆。

        :param workspace_id: 所属工作区 ID。
        :param memory_id: 目标记忆 ID。
        :return: 删除后的记忆记录。
        :raises PersistenceConflictError: 工作区存在活动运行。
        """

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
        """在工作区空闲时物理清空全部记忆。

        :param workspace_id: 目标工作区 ID。
        :return: 实际删除行数。
        :raises PersistenceConflictError: 工作区存在活动运行。
        """

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
        """为尚处于 starting 状态的运行冻结记忆。

        :param run_id: 目标运行 ID。
        :param limit: 最多捕获的记忆条目数。
        :return: 按位置排列的不可变记忆快照记录。
        :raises PersistenceConflictError: 运行已离开 starting 状态或已有快照。
        """

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
        """读取运行创建时冻结的记忆快照。

        :param run_id: 运行 ID。
        :return: 按上下文位置排列的快照记录。
        """

        with self.session_factory() as session:
            RunRepository(session).require(run_id)
            return [
                run_memory_record(item)
                for item in MemoryRepository(session).list_snapshot(run_id)
            ]

    @staticmethod
    def _user_message_for_run(session: Session, run_id: UUID) -> Message | None:
        """在当前事务中查找运行绑定的用户消息。

        :param session: 当前 SQLAlchemy 会话。
        :param run_id: 运行 UUID。
        :return: 活动用户消息实体；不存在时为 None。
        """

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
