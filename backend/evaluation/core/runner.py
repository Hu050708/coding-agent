"""从全新任务副本运行 Agent、外部验收并保存试验结果。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from .catalog import BACKEND_ROOT
from .contracts import (
    CheckResult,
    EvaluationTask,
    TraceSummary,
    TrialResult,
    VerificationResult,
    WorkspaceChanges,
)
from .environment import without_secrets
from .reporter import BenchmarkReporter
from .trace_reader import TraceReader
from .workspace_snapshot import WorkspaceSnapshot


_BUDGET_REASONS = {
    "max_model_calls",
    "max_tool_calls",
    "token_budget_exceeded",
    "wall_time_exceeded",
}


class BenchmarkRunner:
    """顺序执行固定任务，保证每轮工作区相互隔离。"""

    def __init__(self, output: Path, *, python: str | Path = sys.executable) -> None:
        self.output = output.resolve()
        self.python = str(python)
        self.trace_reader = TraceReader()
        self.reporter = BenchmarkReporter()
        self.source_commit, self.source_dirty = self._source_revision()

    def run(
        self,
        tasks: tuple[EvaluationTask, ...],
        *,
        repeats: int,
        model: str,
        wall_time_seconds: float | None = None,
    ) -> tuple[TrialResult, ...]:
        """执行全部任务轮次；单轮运行失败不会丢失其他结果。"""

        self.output.mkdir(parents=True, exist_ok=False)
        trials: list[TrialResult] = []
        for task in tasks:
            for repeat_index in range(1, repeats + 1):
                try:
                    result = self.run_trial(
                        task,
                        repeat_index=repeat_index,
                        model=model,
                        wall_time_seconds=wall_time_seconds,
                    )
                except Exception as exc:
                    result = self._infrastructure_failure(
                        task,
                        repeat_index=repeat_index,
                        model=model,
                        error=type(exc).__name__,
                    )
                    self.reporter.write_trial(
                        self.output / "trials" / result.trial_id,
                        result,
                    )
                trials.append(result)
        self.reporter.write_summary(
            self.output,
            trials,
            model=model,
            source_commit=self.source_commit,
            source_dirty=self.source_dirty,
        )
        return tuple(trials)

    def run_trial(
        self,
        task: EvaluationTask,
        *,
        repeat_index: int,
        model: str,
        wall_time_seconds: float | None = None,
    ) -> TrialResult:
        """复制一个模板，运行现有 Agent CLI，再调用外部 verifier。"""

        started_at = datetime.now(timezone.utc)
        timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        trial_id = f"{task.task_id}-{repeat_index:02d}-{timestamp}-{uuid4().hex[:6]}"
        trial_dir = self.output / "trials" / trial_id
        workspace = trial_dir / "workspace"
        trial_dir.mkdir(parents=True)
        shutil.copytree(
            task.template_dir,
            workspace,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                ".pytest_cache",
                ".coding-agent-traces",
                "*.pyc",
            ),
        )
        initial = WorkspaceSnapshot.capture(workspace)
        task_text = (workspace / "TASK.md").read_text(encoding="utf-8")
        timeout = wall_time_seconds if wall_time_seconds is not None else task.timeout_seconds
        command = [
            self.python,
            "-m",
            "coding_agent",
            "--workspace",
            str(workspace),
            "--model",
            model,
            "--wall-time",
            str(timeout),
            "--yes",
            task_text,
        ]
        environment = os.environ.copy()
        source_path = str(BACKEND_ROOT / "src")
        current_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            source_path + os.pathsep + current_pythonpath if current_pythonpath else source_path
        )
        agent_exit_code: int | None
        try:
            completed = subprocess.run(
                command,
                cwd=BACKEND_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout + 30,
                check=False,
            )
            agent_exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            agent_exit_code = None
            stdout = self._timeout_text(exc.stdout)
            stderr = self._timeout_text(exc.stderr) + "\nouter benchmark timeout"
        (trial_dir / "agent.stdout.log").write_text(stdout, encoding="utf-8", newline="\n")
        (trial_dir / "agent.stderr.log").write_text(stderr, encoding="utf-8", newline="\n")

        trace = self.trace_reader.read_workspace(workspace)
        current = WorkspaceSnapshot.capture(workspace)
        changes = initial.changes_to(current)
        verification = self._run_verifier(task, workspace, timeout=60)
        classification = classify_trial(
            agent_exit_code=agent_exit_code,
            trace=trace,
            verification=verification,
        )
        result = TrialResult(
            schema_version=1,
            trial_id=trial_id,
            task_id=task.task_id,
            task_title=task.title,
            category=task.category,
            repeat_index=repeat_index,
            started_at=started_at.isoformat(timespec="seconds"),
            model_requested=model,
            agent_exit_code=agent_exit_code,
            trace=trace,
            workspace=changes,
            verification=verification,
            classification=classification,
            template_digest=initial.digest,
            source_commit=self.source_commit,
            source_dirty=self.source_dirty,
        )
        self.reporter.write_trial(trial_dir, result)
        return result

    def _run_verifier(
        self,
        task: EvaluationTask,
        workspace: Path,
        *,
        timeout: int,
    ) -> VerificationResult:
        """在不含 API 凭据的独立进程中执行任务验收器。"""

        environment = without_secrets()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                [self.python, "-m", task.verifier_module, str(workspace)],
                cwd=BACKEND_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(False, None, error="verifier_timeout")
        try:
            payload = json.loads(completed.stdout)
            checks = tuple(
                CheckResult(
                    name=str(item["name"]),
                    passed=item["passed"] is True,
                    detail=str(item["detail"]),
                )
                for item in payload["checks"]
            )
            passed = completed.returncode == 0 and payload.get("passed") is True
        except (json.JSONDecodeError, KeyError, TypeError):
            return VerificationResult(
                False,
                completed.returncode,
                error="invalid_verifier_output",
            )
        return VerificationResult(passed, completed.returncode, checks)

    def _infrastructure_failure(
        self,
        task: EvaluationTask,
        *,
        repeat_index: int,
        model: str,
        error: str,
    ) -> TrialResult:
        """把单轮未预期异常转换成仍可汇总的结果。"""

        try:
            digest = WorkspaceSnapshot.capture(task.template_dir).digest
        except OSError:
            digest = "unavailable"
        return TrialResult(
            schema_version=1,
            trial_id=f"{task.task_id}-{repeat_index:02d}-failed",
            task_id=task.task_id,
            task_title=task.title,
            category=task.category,
            repeat_index=repeat_index,
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            model_requested=model,
            agent_exit_code=None,
            trace=TraceSummary(),
            workspace=WorkspaceChanges(),
            verification=VerificationResult(False, None, error="trial_not_verified"),
            classification="evaluation_failure",
            template_digest=digest,
            source_commit=self.source_commit,
            source_dirty=self.source_dirty,
            infrastructure_error=error,
        )

    @staticmethod
    def _timeout_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        return value.decode(errors="replace") if isinstance(value, bytes) else value

    @staticmethod
    def _source_revision() -> tuple[str | None, bool | None]:
        """尽力读取 Git 提交和脏状态，只记录而不阻止评测。"""

        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=BACKEND_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=BACKEND_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        revision = commit.stdout.strip() if commit.returncode == 0 else None
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return revision, dirty


def classify_trial(
    *,
    agent_exit_code: int | None,
    trace: TraceSummary,
    verification: VerificationResult,
) -> str:
    """按照 Agent 终态和独立验收结果区分失败责任。"""

    if verification.error is not None:
        return "evaluation_failure"
    if agent_exit_code == 0 and verification.passed:
        return "success"
    if trace.reason == "api_fatal_error":
        return "provider_failure"
    if trace.reason in _BUDGET_REASONS:
        return "agent_budget_exhausted"
    if agent_exit_code == 0:
        return "incorrect_solution"
    return "agent_runtime_failure"


__all__ = ["BenchmarkRunner", "classify_trial"]
