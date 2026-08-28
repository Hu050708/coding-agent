"""提供工具参数共用的校验函数和结构化错误。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from coding_agent.agents.security import ToolApprovalRequest


class ToolError(Exception):
    """跨工具注册表边界返回的结构化失败。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        data: Mapping[str, Any] | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.data = dict(data) if data is not None else None
        self.meta = dict(meta) if meta is not None else None


ToolConfirmation = Callable[[ToolApprovalRequest], bool]
CancellationCheck = Callable[[], bool]


def reject_unknown(arguments: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ToolError("unknown_argument", f"Unknown argument(s): {', '.join(unknown)}.")


def require_string(
    arguments: Mapping[str, Any],
    name: str,
    *,
    allow_empty: bool = False,
    max_length: int = 4096,
) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ToolError("invalid_argument", f"{name} must be a string.")
    if not allow_empty and not value:
        raise ToolError("invalid_argument", f"{name} may not be empty.")
    if len(value) > max_length:
        raise ToolError("argument_too_large", f"{name} is too long.")
    return value


def optional_string(
    arguments: Mapping[str, Any], name: str, *, default: str | None = None, max_length: int = 4096
) -> str | None:
    if name not in arguments:
        return default
    value = arguments[name]
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ToolError("invalid_argument", f"{name} must be a non-empty string.")
    if len(value) > max_length:
        raise ToolError("argument_too_large", f"{name} is too long.")
    return value


def optional_integer(
    arguments: Mapping[str, Any],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if name not in arguments:
        return default
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("invalid_argument", f"{name} must be an integer.")
    if value < minimum or value > maximum:
        raise ToolError("invalid_argument", f"{name} must be between {minimum} and {maximum}.")
    return value


def optional_number(
    arguments: Mapping[str, Any],
    name: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    if name not in arguments:
        return default
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ToolError("invalid_argument", f"{name} must be a finite number.")
    numeric = float(value)
    if numeric < minimum or numeric > maximum:
        raise ToolError("invalid_argument", f"{name} must be between {minimum} and {maximum}.")
    return numeric


def validate_json_value(value: Any) -> None:
    """递归确认工具参数只包含标准 JSON 可表达的值。"""

    # 标量直接结束；容器递归检查，浮点数额外拒绝 JSON 不支持的非有限值。
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolError("invalid_json_value", "NaN and Infinity are not valid tool arguments.")
        return
    if isinstance(value, list):
        for item in value:
            validate_json_value(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ToolError("invalid_json_value", "JSON object keys must be strings.")
            validate_json_value(item)
        return
    raise ToolError("invalid_json_value", f"Unsupported JSON value type: {type(value).__name__}.")


__all__ = [
    "CancellationCheck",
    "ToolConfirmation",
    "ToolError",
    "optional_integer",
    "optional_number",
    "optional_string",
    "reject_unknown",
    "require_string",
    "validate_json_value",
]
