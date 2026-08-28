"""定义 Web 应用 PostgreSQL 边界使用的稳定持久化枚举。

这些枚举刻意位于智能体核心之外，使核心层无需数据库也能使用，同时让 Web 层
能够存储经过校验的稳定值。
"""

from __future__ import annotations

from enum import StrEnum


class PermissionMode(StrEnum):
    ASK = "ask"
    AGENT = "agent"
    WORKSPACE_FULL = "workspace_full"


class RunStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INTERRUPTED = "interrupted"


ACTIVE_RUN_STATUSES = frozenset(
    {
        RunStatus.STARTING,
        RunStatus.RUNNING,
        RunStatus.WAITING_APPROVAL,
        RunStatus.CANCELLING,
    }
)
TERMINAL_RUN_STATUSES = frozenset(set(RunStatus) - set(ACTIVE_RUN_STATUSES))


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class MemoryKind(StrEnum):
    PREFERENCE = "preference"
    FACT = "fact"
    DECISION = "decision"
    NOTE = "note"


class MemorySource(StrEnum):
    MANUAL = "manual"
    RUN_RESULT = "run_result"


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "ApprovalStatus",
    "MemoryKind",
    "MemorySource",
    "MessageRole",
    "PermissionMode",
    "RunStatus",
]
