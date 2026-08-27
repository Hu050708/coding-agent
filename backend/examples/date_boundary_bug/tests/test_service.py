from datetime import datetime

from logstats.models import LogRecord
from logstats.service import summarize
from logstats.window import DateWindow


def record(timestamp: str, level: str = "INFO") -> LogRecord:
    return LogRecord(timestamp=datetime.fromisoformat(timestamp), level=level)


def test_summarize_all_records_and_sort_levels() -> None:
    result = summarize(
        [record("2026-08-25T12:00:00", "WARNING"), record("2026-08-26T12:00:00")],
        DateWindow(),
    )

    assert result == {"total": 2, "levels": {"INFO": 1, "WARNING": 1}}


def test_from_date_is_inclusive_and_excludes_earlier_records() -> None:
    window = DateWindow.from_cli_dates(start_date="2026-08-25")

    result = summarize(
        [record("2026-08-24T23:59:59"), record("2026-08-25T00:00:00")],
        window,
    )

    assert result == {"total": 1, "levels": {"INFO": 1}}


def test_to_date_includes_a_record_at_midnight() -> None:
    window = DateWindow.from_cli_dates(end_date="2026-08-25")

    result = summarize([record("2026-08-25T00:00:00")], window)

    assert result["total"] == 1
