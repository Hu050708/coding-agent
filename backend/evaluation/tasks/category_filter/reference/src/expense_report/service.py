"""支持可选类别集合的支出统计服务。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .models import Expense
from .records import load_expenses


def summarize(
    expenses: Iterable[Expense],
    categories: set[str] | None = None,
) -> dict[str, object]:
    selected = None if categories is None else set(categories)
    totals: defaultdict[str, int] = defaultdict(int)
    count = 0
    total_cents = 0
    for expense in expenses:
        if selected is not None and expense.category not in selected:
            continue
        count += 1
        total_cents += expense.amount_cents
        totals[expense.category] += expense.amount_cents
    return {
        "count": count,
        "total_cents": total_cents,
        "categories": dict(sorted(totals.items())),
    }


def summarize_file(
    path: Path,
    *,
    categories: set[str] | None = None,
) -> dict[str, object]:
    return summarize(load_expenses(path), categories)
