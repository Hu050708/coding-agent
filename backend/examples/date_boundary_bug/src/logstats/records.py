"""JSONL record loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

from .models import LogRecord


def load_records(path: Path) -> list[LogRecord]:
    """Load validated records from *path*.

    Empty lines are ignored. Invalid input identifies its one-based line number
    so command-line failures are actionable.
    """

    records: list[LogRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            records.append(_parse_record(line, line_number))
    return records


def _parse_record(line: str, line_number: int) -> LogRecord:
    try:
        value = json.loads(line)
        timestamp = value["timestamp"]
        level = value["level"]
        if not isinstance(timestamp, str) or not isinstance(level, str) or not level:
            raise ValueError("timestamp and level must be non-empty strings")
        return LogRecord.from_values(timestamp=timestamp, level=level)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid log record on line {line_number}: {exc}") from exc
