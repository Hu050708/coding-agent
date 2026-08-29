"""支出记录加载测试。"""

import pytest

from expense_report.records import load_expenses


def test_load_expenses_ignores_blank_lines(tmp_path) -> None:
    path = tmp_path / "expenses.jsonl"
    path.write_text('{"category":"food","amount_cents":1200}\n\n', encoding="utf-8")

    assert load_expenses(path)[0].amount_cents == 1200


def test_load_expenses_reports_invalid_line(tmp_path) -> None:
    path = tmp_path / "expenses.jsonl"
    path.write_text('{"category":"food","amount_cents":true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="line 1"):
        load_expenses(path)
