"""Application service for log aggregation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

from .models import LogRecord
from .records import load_records
from .window import DateWindow


def summarize(records: Iterable[LogRecord], window: DateWindow) -> dict[str, object]:
    """Count records selected by *window*, grouped by level."""

    levels = Counter(record.level for record in records if window.contains(record.timestamp))
    return {
        "total": sum(levels.values()),
        "levels": dict(sorted(levels.items())),
    }


def summarize_file(
    path: Path,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, object]:
    """Load *path* and summarize records inside the requested date window."""

    window = DateWindow.from_cli_dates(start_date=from_date, end_date=to_date)
    return summarize(load_records(path), window)
