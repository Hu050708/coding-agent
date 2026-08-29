"""支出汇总测试。"""

from expense_report.models import Expense
from expense_report.service import summarize


def test_summarize_groups_categories_and_total() -> None:
    result = summarize(
        [Expense("travel", 800), Expense("food", 1200), Expense("food", 300)]
    )

    assert result == {
        "count": 3,
        "total_cents": 2300,
        "categories": {"food": 1500, "travel": 800},
    }


def test_summarize_empty_input() -> None:
    assert summarize([]) == {"count": 0, "total_cents": 0, "categories": {}}
