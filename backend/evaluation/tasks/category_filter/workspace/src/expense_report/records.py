"""加载 JSONL 支出记录。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Expense


def load_expenses(path: Path) -> list[Expense]:
    """读取并校验类别和整数金额字段。"""

    expenses: list[Expense] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
            category = value["category"]
            amount_cents = value["amount_cents"]
            if not isinstance(category, str) or not category:
                raise ValueError("category must be a non-empty string")
            if not isinstance(amount_cents, int) or isinstance(amount_cents, bool):
                raise ValueError("amount_cents must be an integer")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid expense on line {line_number}: {exc}") from exc
        expenses.append(Expense(category=category, amount_cents=amount_cents))
    return expenses
