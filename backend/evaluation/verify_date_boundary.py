"""Independent acceptance checks for the ClearLoop date-boundary demo.

Usage:
    python evaluation/verify_date_boundary.py PATH_TO_CANDIDATE

The candidate directory is expected to contain ``src/logstats`` and ``tests``.
Hidden fixtures are created outside that directory and exercised through the
public CLI, so they are never placed in the agent's workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


BASELINE_TEST_COUNT = 4
_SECRET_ENV_SUFFIXES = ("_API_KEY", "_ACCESS_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD")
_SECRET_ENV_NAMES = {"DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _candidate_environment(candidate: Path) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() not in _SECRET_ENV_NAMES
        and not name.upper().endswith(_SECRET_ENV_SUFFIXES)
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    source_path = str(candidate / "src")
    environment["PYTHONPATH"] = source_path
    environment.pop("PYTHONHOME", None)
    return environment


def _run(
    arguments: Sequence[str],
    *,
    candidate: Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        cwd=candidate,
        env=_candidate_environment(candidate),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def check_candidate_tests(candidate: Path) -> CheckResult:
    # Keep pytest's temporary tree beside the isolated candidate instead of
    # relying on the host user's shared temp directory.  On managed Windows
    # runners that directory can contain stale, unreadable pytest folders.
    with tempfile.TemporaryDirectory(
        prefix="clearloop-pytest-",
        dir=candidate.parent,
    ) as raw_basetemp:
        completed = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                raw_basetemp,
            ],
            candidate=candidate,
        )
    detail = (completed.stdout + completed.stderr).strip()
    return CheckResult("candidate test suite", completed.returncode == 0, detail)


def check_regression_test_added(candidate: Path) -> CheckResult:
    with tempfile.TemporaryDirectory(
        prefix="clearloop-collect-",
        dir=candidate.parent,
    ) as raw_basetemp:
        completed = _run(
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
                raw_basetemp,
            ],
            candidate=candidate,
        )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        return CheckResult("regression test added", False, output.strip())

    summary_match = re.search(r"(\d+) tests? collected", output)
    if summary_match is not None:
        count = int(summary_match.group(1))
    else:
        # With the candidate's quiet pytest configuration, collection is
        # rendered as one ``path: count`` line per test module and no summary.
        module_counts = re.findall(r"(?m)^.+:\s+(\d+)\s*$", output)
        count = sum(int(value) for value in module_counts)
    if count == 0:
        return CheckResult(
            "regression test added",
            False,
            "could not determine the collected test count",
        )
    passed = count > BASELINE_TEST_COUNT
    detail = f"collected {count}; baseline is {BASELINE_TEST_COUNT}"
    return CheckResult("regression test added", passed, detail)


def _write_hidden_log(directory: Path) -> Path:
    path = directory / "boundary-events.jsonl"
    events = [
        {"timestamp": "2026-08-24T23:59:59.999999", "level": "DEBUG"},
        {"timestamp": "2026-08-25T00:00:00", "level": "INFO"},
        {"timestamp": "2026-08-25T12:34:56.123456", "level": "ERROR"},
        {"timestamp": "2026-08-25T23:59:59.999999", "level": "INFO"},
        {"timestamp": "2026-08-26T00:00:00", "level": "WARNING"},
    ]
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )
    return path


def _run_cli(candidate: Path, log_file: Path, *arguments: str) -> tuple[int, object, str]:
    completed = _run(
        [sys.executable, "-m", "logstats.cli", str(log_file), *arguments],
        candidate=candidate,
    )
    output = completed.stdout.strip()
    try:
        payload: object = json.loads(output)
    except json.JSONDecodeError:
        payload = None
    return completed.returncode, payload, (completed.stdout + completed.stderr).strip()


def check_end_of_day_contract(candidate: Path, log_file: Path) -> CheckResult:
    code, payload, output = _run_cli(
        candidate,
        log_file,
        "--from",
        "2026-08-25",
        "--to",
        "2026-08-25",
    )
    expected = {"total": 3, "levels": {"ERROR": 1, "INFO": 2}}
    passed = code == 0 and payload == expected
    return CheckResult(
        "inclusive end-of-day and exclusive next midnight",
        passed,
        f"expected {expected!r}; received {payload!r}; output={output!r}",
    )


def check_unfiltered_behavior(candidate: Path, log_file: Path) -> CheckResult:
    code, payload, output = _run_cli(candidate, log_file)
    expected = {
        "total": 5,
        "levels": {"DEBUG": 1, "ERROR": 1, "INFO": 2, "WARNING": 1},
    }
    passed = code == 0 and payload == expected
    return CheckResult(
        "existing unfiltered behavior",
        passed,
        f"expected {expected!r}; received {payload!r}; output={output!r}",
    )


def verify(candidate: Path) -> list[CheckResult]:
    candidate = candidate.resolve()
    required = [candidate / "src" / "logstats", candidate / "tests"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return [CheckResult("candidate layout", False, f"missing: {', '.join(missing)}")]

    results = [
        check_candidate_tests(candidate),
        check_regression_test_added(candidate),
    ]
    with tempfile.TemporaryDirectory(prefix="clearloop-evaluation-") as raw_directory:
        log_file = _write_hidden_log(Path(raw_directory))
        results.extend(
            [
                check_end_of_day_contract(candidate, log_file),
                check_unfiltered_behavior(candidate, log_file),
            ]
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="candidate project directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = verify(args.candidate)
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {result.name}: {result.detail}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
