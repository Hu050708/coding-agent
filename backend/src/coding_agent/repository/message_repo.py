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
        """原子地分配会话消息序号并追加一条消息。"""

        # 第一步：锁定会话行，确保并发追加消息时不会取得相同序号。
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
        # 第二步：使用已分配序号创建消息；会话序号推进和消息写入同属一个事务。
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
        """读取指定位置之前最近的消息，并按正常对话顺序返回。"""

        # 第一步：构造会话范围和可选游标条件。
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
        # 第二步：数据库倒序只取最近一页，再反转为模型需要的时间正序。
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

