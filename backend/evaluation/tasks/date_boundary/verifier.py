"""日期结束边界任务的工作区外黑盒验收器。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from evaluation.core.contracts import CheckResult
from evaluation.core.verifier import BaseVerifier, verifier_main


class DateBoundaryVerifier(BaseVerifier):
    """验收全天结束边界、原行为和新增回归测试。"""

    baseline_test_count = 4
    required_paths = ("src/logstats", "tests")

    def task_checks(self) -> list[CheckResult]:
        with tempfile.TemporaryDirectory(prefix="coding-agent-date-boundary-") as raw_directory:
            log_file = Path(raw_directory) / "boundary-events.jsonl"
            events = [
                {"timestamp": "2026-08-24T23:59:59.999999", "level": "DEBUG"},
                {"timestamp": "2026-08-25T00:00:00", "level": "INFO"},
                {"timestamp": "2026-08-25T12:34:56.123456", "level": "ERROR"},
                {"timestamp": "2026-08-25T23:59:59.999999", "level": "INFO"},
                {"timestamp": "2026-08-26T00:00:00", "level": "WARNING"},
            ]
            log_file.write_text(
                "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
                encoding="utf-8",
            )
            return [
                self._cli_check(
                    "inclusive end-of-day and exclusive next midnight",
                    log_file,
                    {"total": 3, "levels": {"ERROR": 1, "INFO": 2}},
                    "--from",
                    "2026-08-25",
                    "--to",
                    "2026-08-25",
                ),
                self._cli_check(
                    "existing unfiltered behavior",
                    log_file,
                    {
                        "total": 5,
                        "levels": {"DEBUG": 1, "ERROR": 1, "INFO": 2, "WARNING": 1},
                    },
                ),
            ]

    def _cli_check(
        self,
        name: str,
        log_file: Path,
        expected: object,
        *arguments: str,
    ) -> CheckResult:
        completed = self.run_candidate(
            [sys.executable, "-m", "logstats.cli", str(log_file), *arguments]
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = None
        passed = completed.returncode == 0 and payload == expected
        return CheckResult(name, passed, f"expected {expected!r}; received {payload!r}")


def verify(candidate: Path) -> list[CheckResult]:
    """保留供旧脚本和测试调用的函数入口。"""

    return DateBoundaryVerifier(candidate).verify()


def main() -> int:
    return verifier_main(DateBoundaryVerifier)


if __name__ == "__main__":
    raise SystemExit(main())
