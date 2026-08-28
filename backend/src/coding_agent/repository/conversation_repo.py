"""事务级实体仓储。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from coding_agent.models import (
    Approval,
    ApprovalStatus,
    Conversation,
    MemoryEntry,
    MemoryKind,
    MemorySource,
    Message,
    MessageRole,
    PermissionMode,
    Run,
    RunEvent,
    RunMemory,
    RunStatus,
    Workspace,
)

from .base import (
    MAX_MEMORY_CHARS,
    MAX_MEMORY_CONTENT_CHARS,
    MAX_MEMORY_ENTRIES,
    UUIDLike,
    PersistenceConflictError,
    PersistenceNotFoundError,
    _required_text,
    _validate_run_transition,
    as_uuid,
    utc_now,
)
from .safe_events import safe_approval_data, sanitize_run_event
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
        """在同一事务中更新会话可编辑设置。"""

        # 第一步：锁定目标会话，并按请求中实际提供的字段进行部分更新。
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
        # 第二步：统一刷新更新时间，flush 后让调用方拿到最新实体状态。
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

