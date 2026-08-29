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
class RunEventRepository:
    """按运行内序号持久化和分页读取可重放事件。"""

    def __init__(self, session: Session) -> None:
        """绑定当前事务使用的 ORM 会话。

        :param session: 由上层负责事务边界的 SQLAlchemy 会话。
        """

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
        """清洗运行事件并按指定序号持久化，供 SSE 断线重放。

        :param run_id: 事件所属运行 ID。
        :param seq: 运行内严格递增的一基事件序号。
        :param event: 受支持的稳定事件类型。
        :param timestamp: 带时区的事件发生时间。
        :param data: 待按事件白名单清洗的原始数据。
        :return: 已持久化的安全事件实体。
        :raises ValueError: 序号、时间戳或事件数据不合法。
        """

        # 第一步：确认序号和时间戳可用于稳定排序及断点续传。
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise ValueError("seq must be a positive integer")
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        # 第二步：仅保存允许暴露给客户端的字段，再写入事件表。
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
        """分页读取指定序号之后的运行事件。

        :param run_id: 事件所属运行 ID。
        :param after_seq: 仅返回序号严格大于该游标的事件。
        :param limit: 本页期望条数，实际限制在 1 到 5000。
        :return: 按序号升序排列的事件实体列表。
        :raises ValueError: 游标不是非负整数。
        """

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
        """计算运行下一条事件应使用的序号。

        :param run_id: 运行 ID。
        :return: 当前最大序号加一；没有事件时返回 1。
        """

        maximum = self.session.scalar(
            select(func.max(RunEvent.seq)).where(
                RunEvent.run_id == as_uuid(run_id, label="run_id")
            )
        )
        return int(maximum or 0) + 1
