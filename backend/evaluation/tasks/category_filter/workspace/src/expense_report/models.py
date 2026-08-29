"""支出记录领域模型。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Expense:
    """一条使用整数分表示金额的支出。"""

    category: str
    amount_cents: int
