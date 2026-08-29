"""负责日志聚合的应用服务。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

from .models import LogRecord
from .records import load_records
from .window import DateWindow


def summarize(records: Iterable[LogRecord], window: DateWindow) -> dict[str, object]:
    """按级别统计被 ``window`` 选中的日志记录。

    :param records: 可迭代的规范日志记录。
    :param window: 决定每条时间戳是否参与统计的日期窗口。
    :return: 总条数及按名称排序的级别计数字典。
    """

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
    """加载 ``path``，并汇总指定日期窗口内的日志记录。

    :param path: UTF-8 JSONL 日志文件路径。
    :param from_date: 可选起始日，格式为 YYYY-MM-DD。
    :param to_date: 可选结束日，格式为 YYYY-MM-DD。
    :return: 日期窗口内的总条数和级别统计。
    """

    window = DateWindow.from_cli_dates(start_date=from_date, end_date=to_date)
    return summarize(load_records(path), window)
