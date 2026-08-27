"""Date-window construction and membership rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


DATE_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True, slots=True)
class DateWindow:
    """An inclusive, timezone-naive timestamp window."""

    start: datetime | None = None
    end: datetime | None = None

    @classmethod
    def from_cli_dates(
        cls,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> "DateWindow":
        start = _parse_calendar_date(start_date) if start_date else None
        end = _parse_calendar_date(end_date) if end_date else None
        if start is not None and end is not None and start > end:
            raise ValueError("--from must not be later than --to")
        return cls(start=start, end=end)

    def contains(self, timestamp: datetime) -> bool:
        if self.start is not None and timestamp < self.start:
            return False
        if self.end is not None and timestamp > self.end:
            return False
        return True


def _parse_calendar_date(value: str) -> datetime:
    return datetime.strptime(value, DATE_FORMAT)
