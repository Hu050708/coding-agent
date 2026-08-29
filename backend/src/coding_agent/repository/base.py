"""管理 Coding Agent 持久化状态的事务级仓储。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID


from coding_agent.models import (
    RunStatus,
)


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
    """取得带 UTC 时区的当前时间。

    :return: 可直接写入带时区数据库列的当前时间。
    """

    return datetime.now(timezone.utc)


def as_uuid(value: UUIDLike, *, label: str = "id") -> UUID:
    """把 UUID 对象或字符串转换为统一 UUID 类型。

    :param value: UUID 对象或可解析的 UUID 文本。
    :param label: 出错时用于指出具体字段的名称。
    :return: 规范 UUID 对象。
    :raises ValueError: 输入无法解析为 UUID。
    """

    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _required_text(value: str, *, label: str, limit: int | None = None) -> str:
    """校验必填文本并统一去除首尾空白。

    :param value: 待校验的原始文本。
    :param label: 出错信息中使用的字段名称。
    :param limit: 可选的最大字符数。
    :return: 清理后的非空文本。
    :raises ValueError: 输入不是文本、为空或超过长度限制。
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    result = value.strip()
    if limit is not None and len(result) > limit:
        raise ValueError(f"{label} exceeds {limit} characters")
    return result


def _validate_run_transition(current: RunStatus, target: RunStatus) -> None:
    """验证运行状态机是否允许指定迁移。

    :param current: 运行当前状态。
    :param target: 调用方希望写入的目标状态。
    :raises PersistenceConflictError: 当前状态不允许迁移到目标状态。
    """

    if current is target:
        return
    if target not in _RUN_TRANSITIONS.get(current, frozenset()):
        raise PersistenceConflictError(
            f"run cannot transition from {current.value} to {target.value}"
        )


