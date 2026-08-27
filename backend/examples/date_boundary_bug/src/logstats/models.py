"""Domain models for log statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LogRecord:
    """One normalized log entry."""

    timestamp: datetime
    level: str

    @classmethod
    def from_values(cls, *, timestamp: str, level: str) -> "LogRecord":
        """Build a record from values as they appear in JSON input."""

        return cls(timestamp=datetime.fromisoformat(timestamp), level=level)
