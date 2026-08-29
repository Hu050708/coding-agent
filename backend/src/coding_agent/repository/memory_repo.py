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
class MemoryRepository:
    """管理工作区记忆以及绑定到运行的不可变快照。"""

    def __init__(self, session: Session) -> None:
        """绑定当前事务使用的 ORM 会话。

        :param session: 由上层负责事务边界的 SQLAlchemy 会话。
        """

        self.session = session

    @staticmethod
    def content_hash(content: str) -> str:
        """计算去除首尾空白后正文的 SHA-256 哈希。

        :param content: 非空记忆正文。
        :return: 用于活动条目唯一约束的十六进制摘要。
        """

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
        """创建一条经过确认、可参与后续运行上下文的工作区记忆。

        :param workspace_id: 记忆所属工作区 ID。
        :param kind: 记忆业务分类。
        :param content: 不超过配置上限的非空正文。
        :param source: 人工或运行结果来源。
        :param source_run_id: 可选的已完成来源运行 ID。
        :param pinned: 是否在快照选择时优先。
        :param enabled: 是否允许用于后续上下文。
        :return: 已计算哈希并 flush 的记忆实体。
        """

        # 第一步：规范化正文并计算内容哈希，后续可据此识别重复或变更。
        clean_content = _required_text(
            content, label="content", limit=MAX_MEMORY_CONTENT_CHARS
        )
        # 第二步：保存来源、开关和确认时间，事务提交由调用服务控制。
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
        """按 ID 查询记忆并可约束其工作区归属。

        :param memory_id: 记忆 ID。
        :param workspace_id: 可选的所属工作区 ID 限制。
        :param include_deleted: 是否允许返回已软删除记录。
        :param for_update: 是否获取行级写锁。
        :return: 匹配实体；不存在时为 None。
        """

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
        """按优先级列出工作区记忆。

        :param workspace_id: 工作区 ID。
        :param enabled_only: 是否只返回可用于上下文的条目。
        :param limit: 最大条目数，实际限制在 1 到 2000。
        :return: 置顶优先、再按更新时间倒序的记忆列表。
        """

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
        """锁定并部分更新一条工作区记忆。

        :param memory_id: 目标记忆 ID。
        :param workspace_id: 所属工作区 ID，用于阻止跨工作区修改。
        :param kind: 新分类；None 表示不修改。
        :param content: 新正文；None 表示不修改。
        :param pinned: 新置顶状态；None 表示不修改。
        :param enabled: 新启用状态；None 表示不修改。
        :return: 更新并 flush 后的记忆实体。
        :raises PersistenceNotFoundError: 条目不存在或不属于指定工作区。
        """

        # 第一步：限定工作区查找并加行锁，避免跨工作区或并发覆盖。
        item = self.get(memory_id, workspace_id=workspace_id, for_update=True)
        if item is None:
            raise PersistenceNotFoundError("memory entry was not found")
        if kind is not None:
            item.kind = MemoryKind(kind).value
        if content is not None:
            # 正文变化时同步刷新哈希，保持派生字段与内容一致。
            item.content = _required_text(
                content, label="content", limit=MAX_MEMORY_CONTENT_CHARS
            )
            item.content_hash = self.content_hash(item.content)
        if pinned is not None:
            item.pinned = bool(pinned)
        if enabled is not None:
            item.enabled = bool(enabled)
        # 第二步：写入统一更新时间并将修改发送到当前事务。
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def soft_delete(
        self, memory_id: UUIDLike, *, workspace_id: UUIDLike
    ) -> MemoryEntry:
        """软删除并禁用一条工作区记忆。

        :param memory_id: 目标记忆 ID。
        :param workspace_id: 所属工作区 ID。
        :return: 标记删除后的记忆实体。
        :raises PersistenceNotFoundError: 条目不存在或不属于指定工作区。
        """

        item = self.get(memory_id, workspace_id=workspace_id, for_update=True)
        if item is None:
            raise PersistenceNotFoundError("memory entry was not found")
        item.deleted_at = utc_now()
        item.enabled = False
        item.updated_at = item.deleted_at
        self.session.flush()
        return item

    def purge_workspace(self, workspace_id: UUIDLike) -> int:
        """物理删除工作区的所有记忆条目。

        :param workspace_id: 待清理工作区 ID。
        :return: 数据库报告的删除行数。
        """

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
        """为运行创建一次不可变、有字符预算且顺序稳定的记忆快照。

        :param run_id: 接收快照的运行 ID。
        :param workspace_id: 提供候选记忆的工作区 ID。
        :param limit: 最多捕获的条目数，受全局上限约束。
        :param max_content_chars: 所有快照正文允许占用的总字符数。
        :return: 按上下文位置排列的已持久化快照实体。
        :raises PersistenceConflictError: 该运行已经存在不可变快照。
        :raises ValueError: 字符预算不是正整数。
        """

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
        """读取一次运行冻结的项目记忆。

        :param run_id: 运行 ID。
        :return: 按上下文位置升序排列的快照列表。
        """

        return list(
            self.session.scalars(
                select(RunMemory)
                .where(RunMemory.run_id == as_uuid(run_id, label="run_id"))
                .order_by(RunMemory.position)
            )
        )
