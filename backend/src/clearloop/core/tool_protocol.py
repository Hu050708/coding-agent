"""Strict local-tool protocol parsing and result normalization."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from typing import Any


class _DuplicateJSONKey(ValueError):
    pass


def strict_json_object(raw: str) -> dict[str, Any]:
    """Parse a finite JSON object and reject duplicate keys at any depth."""

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
    """Serialize one uniform local-tool failure result."""

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
    """Extract only allowlisted diagnostics from a registry result."""

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
    """Require the registry's uniform JSON-object result before history insertion."""

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


__all__ = [
    "normalize_tool_result",
    "strict_json_object",
    "tool_error",
    "tool_result_metadata",
]
