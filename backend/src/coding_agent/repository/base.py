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


