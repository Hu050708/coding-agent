"""配置优先级任务的工作区外黑盒验收器。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from evaluation.core.contracts import CheckResult
from evaluation.core.verifier import BaseVerifier, verifier_main


class ConfigPrecedenceVerifier(BaseVerifier):
    """验收 CLI、环境和文件来源中的合法 falsey 值。"""

    baseline_test_count = 4
    required_paths = ("src/appconfig", "tests")

    def task_checks(self) -> list[CheckResult]:
        with tempfile.TemporaryDirectory(prefix="coding-agent-config-precedence-") as raw_directory:
            path = Path(raw_directory) / "settings.json"
            path.write_text(
                json.dumps({"retries": 7, "debug": True, "label": "file"}),
                encoding="utf-8",
            )
            return [
                self._cli_check(
                    "CLI falsey values override environment",
                    path,
                    {"retries": 0, "debug": False, "label": ""},
                    {"APP_RETRIES": "5", "APP_DEBUG": "true", "APP_LABEL": "env"},
                    "--retries",
                    "0",
                    "--no-debug",
                    "--label",
                    "",
                ),
                self._cli_check(
                    "environment falsey values override file",
                    path,
                    {"retries": 0, "debug": False, "label": ""},
                    {"APP_RETRIES": "0", "APP_DEBUG": "false", "APP_LABEL": ""},
                ),
                self._cli_check(
                    "existing file behavior",
                    path,
                    {"retries": 7, "debug": True, "label": "file"},
                    {},
                ),
            ]

    def _cli_check(
        self,
        name: str,
        path: Path,
        expected: object,
        environment: dict[str, str],
        *arguments: str,
    ) -> CheckResult:
        completed = self.run_candidate(
            [sys.executable, "-m", "appconfig.cli", str(path), *arguments],
            environment=environment,
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
    return verifier_main(ConfigPrecedenceVerifier)


if __name__ == "__main__":
    raise SystemExit(main())
