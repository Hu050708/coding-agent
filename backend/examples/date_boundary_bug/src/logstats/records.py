"""负责加载并校验 JSONL 日志记录。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import LogRecord


def load_records(path: Path) -> list[LogRecord]:
    """从 *path* 加载经过校验的日志记录。

    空行会被忽略；无效输入会标明从 1 开始的行号，便于定位命令行错误。

    :param path: UTF-8 JSONL 日志文件路径。
    :return: 按文件顺序排列的日志记录。
    :raises OSError: 文件无法打开或读取。
    :raises ValueError: 某个非空行不是合法日志记录。
    """

    records: list[LogRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            records.append(_parse_record(line, line_number))
    return records


def _parse_record(line: str, line_number: int) -> LogRecord:
    """解析并校验一行 JSON 日志。

    :param line: 单行 JSON 文本。
    :param line_number: 用于错误定位的一基文件行号。
    :return: 规范化日志记录。
    :raises ValueError: JSON、必填字段或字段类型无效。
    """

    try:
        value = json.loads(line)
        timestamp = value["timestamp"]
        level = value["level"]
        if not isinstance(timestamp, str) or not isinstance(level, str) or not level:
            raise ValueError("timestamp and level must be non-empty strings")
        return LogRecord.from_values(timestamp=timestamp, level=level)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid log record on line {line_number}: {exc}") from exc
