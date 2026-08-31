"""仅写入白名单字段的轻量诊断事件记录器。

该文件是一个带严格白名单和脱敏规则的 JSONL 运行记录器，
让开发者知道 Agent 做到了哪一步、用了多少资源、工具是否成功，
同时尽量避免把用户内容和敏感信息写进日志。
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
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
            "result_summary",
            "change_check",
        }
    ),
    "run_finished": frozenset(
        {
            "run_id",
            "status",
            "reason",
            "verified",
            "model_calls",
            "tool_calls",
            "usage",
            "duration_ms",
            "change_check",
        }
    ),
}

_USAGE_FIELDS = frozenset(
    {"prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"}
)
_CHANGE_CHECK_FIELDS = frozenset(
    {
        "status",
        "change_version",
        "checked_version",
        "check_kind",
        "tool_sequence",
        "exit_code",
    }
)
_SENSITIVE_NAME = re.compile(
    r"(?:api.?key|authorization|reasoning|prompt|content|stdout|stderr|secret|token_value)",
    re.IGNORECASE,
)


def utc_timestamp() -> str:
    """:return: 毫秒精度、以 ``Z`` 结尾的当前 UTC ISO-8601 时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def summarize_argv(argv: list[str] | tuple[str, ...], *, max_chars: int = 160) -> str:
    """能够判断运行了什么类型的命令和避免泄露命令中的敏感内容。

    :param argv: 已拆分的命令参数序列。
    :param max_chars: 最终摘要允许包含的最大字符数。
    :return: 保留可执行文件名和选项名、隐藏普通参数内容的摘要。
    """

    pieces: list[str] = []
    previous = ""
    for index, raw in enumerate(argv[:12]):
        value = str(raw)
        # 第一个参数只保留程序名称
        if index == 0:
            piece = Path(value).name or "<executable>"
        # 保留命令选项名称
        elif value.startswith("-"):
            piece = value.split("=", 1)[0]
        # 特殊保留 Python 模块名称
        elif previous == "-m" and re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            piece = value
        # 路径只保留文件名
        elif Path(value).suffix and re.fullmatch(r"[A-Za-z0-9_.\\/ -]+", value):
            piece = Path(value).name
        # 其他普通参数进行隐藏
        else:
            piece = Path(value).name if ("/" in value or "\\" in value) else "<arg>"
        # 单个参数最多保留 48 个字符
        pieces.append(piece[:48])
        previous = value
    if len(argv) > 12:
        pieces.append("…")
    # 整个摘要受 max_chars 限制
    return " ".join(pieces)[:max_chars]


def summarize_target(value: Any, *, max_chars: int = 200) -> str | None:
    """把一个可能表示文件或目录路径的值，转换成可以安全写入诊断日志的“工作区相对路径标签”

    :param value: 工具参数或工具结果中的候选路径。
    :param max_chars: 标签允许包含的最大字符数。
    :return: 安全相对路径、``<protected>`` 或 None。
    """

    if not isinstance(value, str) or not value or len(value) > 1_024:
        return None
    if any(ord(character) < 32 for character in value):
        return None
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value.replace("\\", "/"))
    if windows.drive or windows.root or windows.anchor or posix.is_absolute():
        return None
    parts = tuple(part for part in posix.parts if part not in {"", "."})
    if ".." in parts:
        return None
    lowered = {part.casefold() for part in parts}
    if any(
        part == ".env"
        or part.startswith(".env.")
        or Path(part).suffix in {".key", ".pem", ".p12", ".pfx", ".der"}
        for part in lowered
    ):
        return "<protected>"
    normalized = PurePosixPath(*parts).as_posix() if parts else "."
    return normalized[:max_chars]


def _safe_usage(value: Any) -> dict[str, int]:
    """筛选允许写入诊断日志的非负 Token 用量。

    :param value: 候选用量映射。
    :return: 只包含白名单用量字段的普通字典。
    """

    if not isinstance(value, Mapping):
        return {}
    return {
        key: item
        for key in _USAGE_FIELDS
        if isinstance((item := value.get(key)), int) and not isinstance(item, bool) and item >= 0
    }


def _safe_value(key: str, value: Any) -> Any:
    """把单个事件字段规范化为可安全序列化的值。

    :param key: 事件字段名称。
    :param value: 调用方提供的原始字段值。
    :return: 白名单用量字典、JSON 标量或不可信对象的字符串表示。
    """

    if key == "usage":
        return _safe_usage(value)
    if key == "change_check" and isinstance(value, Mapping):
        return {
            field: item
            for field in _CHANGE_CHECK_FIELDS
            if (item := value.get(field)) is None
            or isinstance(item, (str, int))
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class TraceWriter:
    """以 JSON Lines 记录追加五种受支持事件。"""

    def __init__(self, path: str | Path | None = None, *, stream: TextIO | None = None) -> None:
        """创建文件和/或文本流诊断写入器。

        :param path: 可选 JSONL 文件路径；写入前会解析为绝对路径。
        :param stream: 可选文本流，适合把同一事件同步输出到终端。
        """

        # 诊断 JSONL 的绝对输出路径；为空时不写文件。
        self.path = Path(path).resolve() if path is not None else None
        # 可选镜像输出流。
        self.stream = stream
        self._lock = threading.Lock()

    def emit(self, event: str, /, **fields: Any) -> dict[str, Any]:
        """筛选并追加一条不含敏感字段的诊断事件。

        :param event: ``EVENT_FIELDS`` 中声明的事件名称。
        :param fields: 候选结构化字段；未知或敏感字段会被丢弃。
        :return: 实际写入文件或流的安全事件记录。
        :raises ValueError: 事件名称不在支持列表中。
        """

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
        """创建不写文件也不写流的空诊断接收器。"""

        super().__init__()
