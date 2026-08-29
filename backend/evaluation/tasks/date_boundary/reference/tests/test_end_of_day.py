"""日末边界回归测试。"""

from datetime import datetime

from logstats.window import DateWindow


def test_to_date_covers_last_microsecond_but_not_next_midnight() -> None:
    window = DateWindow.from_cli_dates(end_date="2026-08-25")

    assert window.contains(datetime.fromisoformat("2026-08-25T23:59:59.999999"))
    assert not window.contains(datetime.fromisoformat("2026-08-26T00:00:00"))
