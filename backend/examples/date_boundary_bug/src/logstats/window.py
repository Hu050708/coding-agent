"""定义日期窗口的构建和成员判断规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


DATE_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True, slots=True)
class DateWindow:
    """包含两端点且不携带时区的时间戳窗口。"""

    # 可选包含式起始时间；None 表示没有下界。
    start: datetime | None = None
    # 可选包含式结束时间；None 表示没有上界。
    end: datetime | None = None

    @classmethod
    def from_cli_dates(
        cls,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> "DateWindow":
        """从 CLI 日历日期构建时间窗口。

        :param start_date: 可选 YYYY-MM-DD 起始日期。
        :param end_date: 可选 YYYY-MM-DD 结束日期。
        :return: 解析后的日期窗口。
        :raises ValueError: 日期格式错误或起始值晚于结束值。
        """

        start = _parse_calendar_date(start_date) if start_date else None
        end = _parse_calendar_date(end_date) if end_date else None
        if start is not None and end is not None and start > end:
            raise ValueError("--from must not be later than --to")
        return cls(start=start, end=end)

    def contains(self, timestamp: datetime) -> bool:
        """判断时间戳是否位于当前包含式边界内。

        :param timestamp: 待检查的无时区时间戳。
        :return: 未越过已配置上下界时为 True。
        """

        if self.start is not None and timestamp < self.start:
            return False
        if self.end is not None and timestamp > self.end:
            return False
        return True


def _parse_calendar_date(value: str) -> datetime:
    """将 YYYY-MM-DD 日历日期解析为当天零点。

    :param value: 日历日期文本。
    :return: 对应当天 00:00:00 的无时区时间对象。
    :raises ValueError: 文本不符合指定日期格式。
    """

    return datetime.strptime(value, DATE_FORMAT)
