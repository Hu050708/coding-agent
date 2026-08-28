"""仅写入白名单字段的轻量诊断事件记录器。

这是调试跟踪而非审计日志，绝不记录提示词、模型推理、文件内容、命令输出或
API 凭据。调用方必须在发送前把模型选择的工具名等不可信标识映射为已知安全
标签；本记录器刻意不了解工具模型。
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
        {
            "run_id",
            "sequence",
            "tool",
            "ok",
            "error_code",
            "exit_code",
            "duration_ms",
            "truncated",
            "repeat_count",
            "progress_warning",
        }
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
    """为诊断事件生成刻意有损的命令摘要。"""

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
    """以 JSON Lines 记录追加五种受支持事件。"""

    def __init__(self, path: str | Path | None = None, *, stream: TextIO | None = None) -> None:
        self.path = Path(path).resolve() if path is not None else None
        self.stream = stream
        self._lock = threading.Lock()

    def emit(self, event: str, /, **fields: Any) -> dict[str, Any]:
        """筛选并追加一条不含敏感字段的诊断事件。"""

        # 第一步：只接收预先声明的事件类型和字段，并对字段值进行安全归一化。
        if event not in EVENT_FIELDS:
            raise ValueError(f"unsupported diagnostic event: {event}")

        record: dict[str, Any] = {"timestamp": utc_timestamp(), "event": event}
        for key, value in fields.items():
            if key in EVENT_FIELDS[event] and not _SENSITIVE_NAME.search(key):
                record[key] = _safe_value(key, value)

        # 第二步：在同一把锁内写文件和可选流，保证并发运行不会交叉写坏 JSONL。
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
    """丢弃诊断事件，同时保持相同接口。"""

    def __init__(self) -> None:
        super().__init__()
