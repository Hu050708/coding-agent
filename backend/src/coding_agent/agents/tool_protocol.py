"""严格解析本地工具协议并规范化工具结果。"""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from typing import Any


class _DuplicateJSONKey(ValueError):
    pass


def strict_json_object(raw: str) -> dict[str, Any]:
    """解析有限 JSON 对象，并拒绝任意层级的重复键。"""

    # 第一步：通过解析钩子拒绝非有限常量和任意层级的重复键。
    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJSONKey(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(
        raw,
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")

    # 第二步：递归复核解析结果，防止嵌套结构携带非有限浮点数。
    def reject_nonfinite(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("tool arguments contain a non-finite number")
        if isinstance(item, Mapping):
            for nested in item.values():
                reject_nonfinite(nested)
        elif isinstance(item, list):
            for nested in item:
                reject_nonfinite(nested)

    reject_nonfinite(value)
    return value


def tool_error(code: str, message: str, *, retryable: bool = False) -> str:
    """序列化统一格式的本地工具失败结果。"""

    return json.dumps(
        {
            "ok": False,
            "error": {"code": code, "message": message, "retryable": retryable},
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def tool_result_metadata(
    result: str,
) -> tuple[bool, str | None, int | None, bool | None]:
    """仅从注册表结果中提取白名单诊断字段。"""

    # 第一步：把非 JSON、非对象和错误字段缺失都视为无效工具结果。
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return False, "invalid_tool_result", None, None
    if not isinstance(payload, Mapping):
        return False, "invalid_tool_result", None, None
    ok = payload.get("ok") is True
    error_code: str | None = None
    error = payload.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("code"), str):
        error_code = error["code"]
    data = payload.get("data")
    meta = payload.get("meta")
    exit_code: int | None = None
    truncated: bool | None = None
    # 第二步：只提取退出码和截断标志，不允许工具结果任意字段进入诊断事件。
    if isinstance(data, Mapping):
        value = data.get("exit_code")
        if isinstance(value, int) and not isinstance(value, bool):
            exit_code = value
    if isinstance(meta, Mapping):
        value = meta.get("truncated")
        if isinstance(value, bool):
            truncated = value
        else:
            stdout_truncated = meta.get("stdout_truncated")
            stderr_truncated = meta.get("stderr_truncated")
            if isinstance(stdout_truncated, bool) and isinstance(stderr_truncated, bool):
                truncated = stdout_truncated or stderr_truncated
    return ok, error_code, exit_code, truncated


def normalize_tool_result(result: Any) -> str:
    """写入历史前，确保注册表返回统一的 JSON 对象结果。"""

    if not isinstance(result, str):
        return tool_error(
            "invalid_tool_result",
            "tool registry returned a non-string result",
        )
    try:
        payload = strict_json_object(result)
    except (TypeError, ValueError, RecursionError):
        return tool_error(
            "invalid_tool_result",
            "tool registry returned invalid JSON",
        )
    if not isinstance(payload.get("ok"), bool):
        return tool_error(
            "invalid_tool_result",
            "tool registry result must contain a boolean ok field",
        )
    return result


def add_progress_warning(result: str, *, repeat_count: int) -> str:
    """Attach one advisory warning without changing the original result status."""

    payload = strict_json_object(result)
    raw_meta = payload.get("meta")
    meta = dict(raw_meta) if isinstance(raw_meta, Mapping) else {}
    meta["progress_warning"] = {
        "code": "repeated_tool_exchange",
        "repeat_count": repeat_count,
        "message": (
            "This exact tool call has produced the same result repeatedly. "
            "Inspect the result and change approach before retrying."
        ),
    }
    payload["meta"] = meta
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


__all__ = [
    "add_progress_warning",
    "normalize_tool_result",
    "strict_json_object",
    "tool_error",
    "tool_result_metadata",
]
