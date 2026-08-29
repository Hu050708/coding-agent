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
class ApprovalRepository:
    """管理工具审批的创建、锁定和一次性状态转换。"""

    def __init__(self, session: Session) -> None:
        """绑定当前事务使用的 ORM 会话。

        :param session: 由上层负责提交或回滚的 SQLAlchemy 会话。
        """

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
        """创建一条等待用户处理的工具审批记录。

        :param approval_id: 运行时预先生成的审批 ID。
        :param run_id: 触发危险操作的运行 ID。
        :param tool_name: 请求执行的工具名称。
        :param action_summary: 面向用户的简短操作摘要。
        :param reason: 安全策略要求审批的原因。
        :param expires_at: 带时区的自动过期时间。
        :return: 已清洗展示字段并 flush 的待审批实体。
        :raises ValueError: 过期时间不含时区或展示字段不安全。
        """

        # 第一步：规范化展示给用户的工具信息，避免运行时事件与数据库内容不一致。
        if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        safe = safe_approval_data(
            tool_name=tool_name, action_summary=action_summary, reason=reason
        )
        # 第二步：以 pending 作为唯一初始状态，写入后立即 flush 取得数据库结果。
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
        """按 ID 查询审批记录。

        :param approval_id: 审批 ID。
        :param for_update: 是否为状态修改获取行级写锁。
        :return: 匹配实体；不存在时为 None。
        """

        statement = select(Approval).where(
            Approval.id == as_uuid(approval_id, label="approval_id")
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def pending_for_run(self, run_id: UUIDLike) -> Approval | None:
        """查询运行当前唯一的待处理审批。

        :param run_id: 运行 ID。
        :return: 待处理审批；没有时为 None。
        """

        return self.session.scalar(
            select(Approval).where(
                Approval.run_id == as_uuid(run_id, label="run_id"),
                Approval.status == ApprovalStatus.PENDING.value,
            )
        )

    def resolve(
        self, approval_id: UUIDLike, *, status: ApprovalStatus | str
    ) -> Approval:
        """以行锁把待审批记录一次性转换为最终状态。

        :param approval_id: 待处理审批 ID。
        :param status: 同意、拒绝、过期或取消等终结状态。
        :return: 更新后的审批实体。
        :raises PersistenceNotFoundError: 审批不存在。
        :raises PersistenceConflictError: 审批已被其他请求处理。
        :raises ValueError: 目标状态仍为 pending。
        """

        # 第一步：锁定记录，防止两个确认请求同时修改同一条审批。
        item = self.get(approval_id, for_update=True)
        if item is None:
            raise PersistenceNotFoundError("approval was not found")
        if item.status != ApprovalStatus.PENDING.value:
            raise PersistenceConflictError("approval is no longer pending")
        value = ApprovalStatus(status)
        if value is ApprovalStatus.PENDING:
            raise ValueError("pending is not a resolution")
        # 第二步：同时记录结果和完成时间；提交事务由上层服务统一负责。
        item.status = value.value
        item.resolved_at = utc_now()
        item.updated_at = item.resolved_at
        self.session.flush()
        return item
