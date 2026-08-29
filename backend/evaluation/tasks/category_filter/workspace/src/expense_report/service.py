"""支出统计服务。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .models import Expense
from .records import load_expenses


def summarize(expenses: Iterable[Expense]) -> dict[str, object]:
    """汇总全部支出，并按类别名称稳定排序。"""

    categories: defaultdict[str, int] = defaultdict(int)
    count = 0
    total_cents = 0
    for expense in expenses:
        count += 1
        total_cents += expense.amount_cents
        categories[expense.category] += expense.amount_cents
    return {
        "count": count,
        "total_cents": total_cents,
        "categories": dict(sorted(categories.items())),
    }


def summarize_file(path: Path) -> dict[str, object]:
    """加载一个 JSONL 文件并汇总全部记录。"""

    return summarize(load_expenses(path))
