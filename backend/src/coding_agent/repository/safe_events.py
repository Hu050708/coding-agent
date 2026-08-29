"""对持久化、可重放运行事件执行防御性投影。

实时事件缓冲区可能携带额外的瞬时值。本模块是写入 ``run_events`` 的唯一入口，
只允许工作区相对目标和有损命令摘要，主动丢弃绝对路径、完整命令参数、文件正文、
工具输出和供应商元数据。
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from typing import Any


class UnsafeEventError(ValueError):
    """事件无法用公共安全模型表示时抛出。"""


_SCALAR_KEYS: dict[str, frozenset[str]] = {
    "run.accepted": frozenset({"run_id", "status"}),
    "run.started": frozenset({"run_id", "status"}),
    "run.interrupted": frozenset({"run_id", "status", "reason"}),
    "run.finished": frozenset(
        {
            "run_id",
            "status",
            "reason",
            "model_calls",
            "tool_calls",
            "duration_seconds",
        }
    ),
    "run.error": frozenset({"run_id", "code", "message"}),
    "memory.loaded": frozenset({"status", "loaded_count"}),
    "model.completed": frozenset(
        {
            "sequence",
            "model",
            "response_model",
            "finish_reason",
            "latency_ms",
            "retry_count",
        }
    ),
    "tool.started": frozenset(
        {"sequence", "tool_name", "target", "argv_summary"}
    ),
    "tool.completed": frozenset(
        {
            "sequence",
            "tool_name",
            "ok",
            "error_code",
            "exit_code",
            "duration_ms",
            "truncated",
            "repeat_count",
            "progress_warning",
            "result_summary",
        }
    ),
    "approval.required": frozenset({"run_id"}),
    "approval.resolved": frozenset(
        {"run_id", "approval_id", "decision", "resolution"}
    ),
    "message.created": frozenset({"message_id", "role", "seq"}),
}
_NESTED_KEYS: dict[str, dict[str, frozenset[str]]] = {
    "run.finished": {
        "usage": frozenset(
            {
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
            }
        ),
        "change_check": frozenset(
            {
                "status",
                "change_version",
                "checked_version",
                "check_kind",
                "tool_sequence",
                "exit_code",
            }
        ),
    },
    "model.completed": {
        "usage": frozenset(
            {
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
            }
        )
    },
    "memory.loaded": {"loaded_ids": frozenset()},
    "approval.required": {
        "approval": frozenset(
            {"approval_id", "reason", "created_at", "expires_at"}
        )
    },
    "tool.completed": {
        "change_check": frozenset(
            {
                "status",
                "change_version",
                "checked_version",
                "check_kind",
                "tool_sequence",
                "exit_code",
            }
        )
    },
}
_MAX_STRING = 2_000
_MAX_LIST_ITEMS = 200


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    """将值限制为 JSON 安全标量并截断过长文本。

    :param value: 待写入持久化事件字段的原始值。
    :return: 允许的 JSON 标量。
    :raises UnsafeEventError: 值类型不允许或浮点数非有限。
    """

    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            return value[:_MAX_STRING]
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise UnsafeEventError("event numbers must be finite")
        return value
    raise UnsafeEventError("event fields must be JSON scalars")


def sanitize_run_event(event: str, data: Mapping[str, Any] | None) -> dict[str, Any]:
    """返回一个已知事件的安全公共投影。

    未知事件名会被拒绝，而不是乐观持久化；已知事件上的未知字段会被丢弃。
    因此实时流后续新增字段必须显式加入白名单，才能进入持久化存储。

    :param event: 稳定的运行事件类型名称。
    :param data: 实时事件携带的原始字段映射。
    :return: 仅包含该事件白名单字段的独立 JSON 对象。
    :raises UnsafeEventError: 事件未知、负载结构错误或字段值不安全。
    """

    # 第一步：验证事件名和顶层负载类型，只复制该事件允许的标量字段。
    if event not in _SCALAR_KEYS:
        raise UnsafeEventError(f"unsupported persisted event: {event!r}")
    if data is None:
        source: Mapping[str, Any] = {}
    elif isinstance(data, Mapping):
        source = data
    else:
        raise UnsafeEventError("event data must be an object")

    result: dict[str, Any] = {}
    for key in _SCALAR_KEYS[event]:
        if key in source:
            result[key] = _safe_scalar(source[key])

    # 第二步：按各嵌套对象的独立白名单投影，并限制字符串列表的数量与长度。
    for key, allowed_nested in _NESTED_KEYS.get(event, {}).items():
        value = source.get(key)
        if value is None:
            continue
        if key == "loaded_ids":
            if not isinstance(value, (list, tuple)):
                raise UnsafeEventError("loaded_ids must be a list")
            result[key] = [
                item[:_MAX_STRING]
                for item in value[:_MAX_LIST_ITEMS]
                if isinstance(item, str)
            ]
            continue
        if not isinstance(value, Mapping):
            raise UnsafeEventError(f"{key} must be an object")
        result[key] = {
            nested_key: _safe_scalar(value[nested_key])
            for nested_key in allowed_nested
            if nested_key in value
        }

    # 第三步：防御性 JSON 往返可捕获驱动可能隐式转换的值，并返回与调用方结构脱离的对象。
    return json.loads(
        json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )


def safe_approval_data(
    *, tool_name: str, action_summary: str, reason: str
) -> dict[str, str]:
    """构建持久化存储唯一允许保存的审批负载。

    原始 argv、cwd、stdin、环境变量值和工具输出会被主动排除；这些值只能短暂存在于
    实时审批代理中。

    :param tool_name: 待审批工具名称。
    :param action_summary: 面向用户的操作摘要。
    :param reason: 需要审批的安全原因。
    :return: 仅含三项安全展示文本的独立字典。
    :raises UnsafeEventError: 任一展示字段不是非空文本。
    """

    values = {
        "tool_name": tool_name,
        "action_summary": action_summary,
        "reason": reason,
    }
    # 第一步：逐项确认展示字段是非空文本，并限制数据库中的最大长度。
    result: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise UnsafeEventError(f"{key} must be non-empty text")
        result[key] = value.strip()[:1_000]
    # 第二步：返回新字典，不携带调用方可能附加的命令和环境字段。
    return result


__all__ = ["UnsafeEventError", "safe_approval_data", "sanitize_run_event"]
