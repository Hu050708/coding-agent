"""类别筛选任务的工作区外黑盒验收器。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from evaluation.core.contracts import CheckResult
from evaluation.core.verifier import BaseVerifier, verifier_main


class CategoryFilterVerifier(BaseVerifier):
    """验收单类别、多类别、空结果和原有未筛选行为。"""

    baseline_test_count = 4
    required_paths = ("src/expense_report", "tests")

    def task_checks(self) -> list[CheckResult]:
        with tempfile.TemporaryDirectory(prefix="coding-agent-category-filter-") as raw_directory:
            path = Path(raw_directory) / "expenses.jsonl"
            rows = [
                {"category": "food", "amount_cents": 1200},
                {"category": "travel", "amount_cents": 800},
                {"category": "food", "amount_cents": 300},
                {"category": "books", "amount_cents": 2500},
            ]
            path.write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
                encoding="utf-8",
            )
            return [
                self._cli_check(
                    "single category",
                    path,
                    {"count": 2, "total_cents": 1500, "categories": {"food": 1500}},
                    "--category",
                    "food",
                ),
                self._cli_check(
                    "multiple categories",
                    path,
                    {
                        "count": 3,
                        "total_cents": 2300,
                        "categories": {"food": 1500, "travel": 800},
                    },
                    "--category",
                    "food",
                    "--category",
                    "travel",
                    "--category",
                    "food",
                ),
                self._cli_check(
                    "missing category is empty",
                    path,
                    {"count": 0, "total_cents": 0, "categories": {}},
                    "--category",
                    "missing",
                ),
                self._cli_check(
                    "existing unfiltered behavior",
                    path,
                    {
                        "count": 4,
                        "total_cents": 4800,
                        "categories": {"books": 2500, "food": 1500, "travel": 800},
                    },
                ),
            ]

    def _cli_check(
        self,
        name: str,
        path: Path,
        expected: object,
        *arguments: str,
    ) -> CheckResult:
        completed = self.run_candidate(
            [sys.executable, "-m", "expense_report.cli", str(path), *arguments]
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = None
        return CheckResult(
            name,
            completed.returncode == 0 and payload == expected,
            f"expected {expected!r}; received {payload!r}",
        )


def main() -> int:
    return verifier_main(CategoryFilterVerifier)


if __name__ == "__main__":
    raise SystemExit(main())
