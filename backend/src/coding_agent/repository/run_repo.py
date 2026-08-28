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
        """创建处于 starting 状态的 Agent 运行记录。"""

        # 第一步：固化本次运行使用的工作区、会话、权限和记忆开关。
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
        # 第二步：flush 使运行编号可立即用于消息、事件和审批等关联记录。
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
        """校验运行状态机并更新状态及相关时间字段。"""

        # 第一步：锁定运行并拒绝状态机未允许的跳转。
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
            # 进入任意终态时，如调用方未指定时间则由仓储记录当前完成时间。
            item.finished_at = utc_now()
        # 第二步：统一更新时间并刷新当前事务。
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

