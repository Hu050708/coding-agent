"""类别筛选回归测试。"""

from expense_report.models import Expense
from expense_report.service import summarize


def test_summarize_selects_multiple_categories() -> None:
    expenses = [Expense("food", 100), Expense("travel", 200), Expense("books", 300)]

    assert summarize(expenses, {"food", "travel"}) == {
        "count": 2,
        "total_cents": 300,
        "categories": {"food": 100, "travel": 200},
    }
