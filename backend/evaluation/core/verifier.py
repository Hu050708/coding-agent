"""三个评测任务共用的候选测试与外部验收基础设施。"""

from __future__ import annotations

from abc import ABC, abstractmethod
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence

from .contracts import CheckResult
from .environment import candidate_environment


class BaseVerifier(ABC):
    """先验收候选测试，再执行任务专属黑盒检查。"""

    baseline_test_count: int
    required_paths: tuple[str, ...] = ("src", "tests")

    def __init__(self, candidate: Path) -> None:
        self.candidate = candidate.resolve()

    def run_candidate(
        self,
        arguments: Sequence[str],
        *,
        timeout: int = 30,
        environment: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """在候选目录中运行一个不携带宿主凭据的子进程。"""

        return subprocess.run(
            list(arguments),
            cwd=self.candidate,
            env=candidate_environment(self.candidate, additions=environment),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def candidate_tests(self) -> CheckResult:
        """运行候选项目自己的完整 pytest 测试套件。"""

        with tempfile.TemporaryDirectory(prefix="coding-agent-pytest-") as base_temp:
            completed = self.run_candidate(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    base_temp,
                ]
            )
        detail = (completed.stdout + completed.stderr).strip()
        return CheckResult("candidate test suite", completed.returncode == 0, detail)

    def regression_test_added(self) -> CheckResult:
        """确认候选收集到的测试数超过任务基线。"""

        with tempfile.TemporaryDirectory(prefix="coding-agent-collect-") as base_temp:
            completed = self.run_candidate(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests",
                    "--collect-only",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    base_temp,
                ]
            )
        output = completed.stdout + completed.stderr
        if completed.returncode != 0:
            return CheckResult("regression test added", False, output.strip())

        match = re.search(r"(\d+) tests? collected", output)
        if match is not None:
            count = int(match.group(1))
        else:
            count = sum(int(value) for value in re.findall(r"(?m)^.+:\s+(\d+)\s*$", output))
        passed = count > self.baseline_test_count
        return CheckResult(
            "regression test added",
            passed,
            f"collected {count}; baseline is {self.baseline_test_count}",
        )

    def verify(self) -> list[CheckResult]:
        """执行目录、候选测试、测试增量和任务专属检查。"""

        missing = [
            str(self.candidate / relative)
            for relative in self.required_paths
            if not (self.candidate / relative).exists()
        ]
        if missing:
            return [CheckResult("candidate layout", False, f"missing: {', '.join(missing)}")]
        return [
            self.candidate_tests(),
            self.regression_test_added(),
            *self.task_checks(),
        ]

    @abstractmethod
    def task_checks(self) -> list[CheckResult]:
        """返回当前任务的独立业务检查。"""


def verifier_main(verifier_type: type[BaseVerifier], argv: Sequence[str] | None = None) -> int:
    """运行一个任务 verifier，并向 stdout 输出唯一 JSON 对象。"""

    parser = argparse.ArgumentParser(description=verifier_type.__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    checks = verifier_type(args.candidate).verify()
    payload = {
        "passed": all(check.passed for check in checks),
        "checks": [check.as_dict() for check in checks],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["passed"] else 1


__all__ = ["BaseVerifier", "candidate_environment", "verifier_main"]
