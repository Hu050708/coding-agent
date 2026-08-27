"""Small, allowlist-only diagnostic event writer.

This is a debugging trace, not an audit log. It never records prompts, model
reasoning, file contents, command output, or API credentials. Callers must map
untrusted identifiers, such as model-selected tool names, to known safe labels
before emitting them; this writer deliberately does not know tool schemas.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any, Mapping, TextIO


EVENT_FIELDS: dict[str, frozenset[str]] = {
    "run_started": frozenset(
        {"run_id", "workspace", "model", "max_model_calls", "max_tool_calls", "wall_time_seconds"}
    ),
    "model_completed": frozenset(
        {
            "run_id", "sequence", "model", "response_model", "system_fingerprint",
            "finish_reason", "latency_ms", "usage", "retry_count",
        }
    ),
    "tool_started": frozenset({"run_id", "sequence", "tool", "target", "argv_summary"}),
    "tool_completed": frozenset(
        {"run_id", "sequence", "tool", "ok", "error_code", "exit_code", "duration_ms", "truncated"}
    ),
    "run_finished": frozenset(
        {"run_id", "status", "reason", "verified", "model_calls", "tool_calls", "usage", "duration_ms"}
    ),
}

_USAGE_FIELDS = frozenset(
    {"prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"}
)
_SENSITIVE_NAME = re.compile(
    r"(?:api.?key|authorization|reasoning|prompt|content|stdout|stderr|secret|token_value)",
    re.IGNORECASE,
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def summarize_argv(argv: list[str] | tuple[str, ...], *, max_chars: int = 160) -> str:
    """Return a deliberately lossy command summary for diagnostic events."""

    pieces: list[str] = []
    for index, raw in enumerate(argv[:12]):
        value = str(raw)
        if index == 0:
            piece = Path(value).name or "<executable>"
        elif value.startswith("-"):
            piece = value.split("=", 1)[0]
        else:
            piece = Path(value).name if ("/" in value or "\\" in value) else "<arg>"
        pieces.append(piece[:48])
    if len(argv) > 12:
        pieces.append("…")
    return " ".join(pieces)[:max_chars]


def _safe_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: item
        for key in _USAGE_FIELDS
        if isinstance((item := value.get(key)), int) and not isinstance(item, bool) and item >= 0
    }


def _safe_value(key: str, value: Any) -> Any:
    if key == "usage":
        return _safe_usage(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class TraceWriter:
    """Append the five supported event types as JSON Lines records."""

    def __init__(self, path: str | Path | None = None, *, stream: TextIO | None = None) -> None:
        self.path = Path(path).resolve() if path is not None else None
        self.stream = stream
        self._lock = threading.Lock()

    def emit(self, event: str, /, **fields: Any) -> dict[str, Any]:
        if event not in EVENT_FIELDS:
            raise ValueError(f"unsupported diagnostic event: {event}")

        record: dict[str, Any] = {"timestamp": utc_timestamp(), "event": event}
        for key, value in fields.items():
            if key in EVENT_FIELDS[event] and not _SENSITIVE_NAME.search(key):
                record[key] = _safe_value(key, value)

        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with self._lock:
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
            if self.stream is not None:
                self.stream.write(line + "\n")
                self.stream.flush()
        return record


class NullTrace(TraceWriter):
    """Drop diagnostic events while retaining the same interface."""

    def __init__(self) -> None:
        super().__init__()
