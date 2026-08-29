"""验证评测 trace、工作区快照、分类和报告聚合。"""

from __future__ import annotations

import json

from evaluation.core.contracts import (
    CheckResult,
    TraceSummary,
    TrialResult,
    VerificationResult,
    WorkspaceChanges,
)
from evaluation.core.reporter import BenchmarkReporter
from evaluation.core.runner import classify_trial
from evaluation.core.trace_reader import TraceReader
from evaluation.core.workspace_snapshot import WorkspaceSnapshot


def test_trace_reader_aggregates_only_safe_runtime_metrics(tmp_path) -> None:
    trace = tmp_path / "run.jsonl"
    records = [
        {"event": "run_started", "model": "deepseek-v4-flash"},
        {
            "event": "model_completed",
            "response_model": "deepseek-v4-flash-202608",
            "system_fingerprint": "fp-1",
            "usage": {"total_tokens": 12},
        },
        {"event": "tool_completed", "tool": "read_file", "ok": True},
        {
            "event": "tool_completed",
            "tool": "run_command",
            "ok": False,
            "error_code": "command_exit_nonzero",
            "progress_warning": True,
        },
        {
            "event": "run_finished",
            "status": "model_finished",
            "reason": "model_final",
            "verified": "unknown",
            "model_calls": 1,
            "tool_calls": 2,
            "usage": {"total_tokens": 12},
            "duration_ms": 1250,
        },
    ]
    trace.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n{broken",
        encoding="utf-8",
    )

    result = TraceReader().read(trace)

    assert result.model_calls == 1
    assert result.tool_calls == 2
    assert result.successful_tools == 1
    assert result.failed_tools == 1
    assert result.tool_counts == {"read_file": 1, "run_command": 1}
    assert result.error_counts == {"command_exit_nonzero": 1}
    assert result.repeat_warnings == 1
    assert result.response_models == ("deepseek-v4-flash-202608",)


def test_workspace_snapshot_reports_changes_and_ignores_runtime_files(tmp_path) -> None:
    (tmp_path / "keep.py").write_text("old", encoding="utf-8")
    (tmp_path / "delete.py").write_text("delete", encoding="utf-8")
    before = WorkspaceSnapshot.capture(tmp_path)

    (tmp_path / "keep.py").write_text("new", encoding="utf-8")
    (tmp_path / "delete.py").unlink()
    (tmp_path / "added.py").write_text("added", encoding="utf-8")
    trace_dir = tmp_path / ".coding-agent-traces"
    trace_dir.mkdir()
    (trace_dir / "run.jsonl").write_text("{}", encoding="utf-8")

    changes = before.changes_to(WorkspaceSnapshot.capture(tmp_path))

    assert changes.added == ("added.py",)
    assert changes.modified == ("keep.py",)
    assert changes.deleted == ("delete.py",)


def test_trial_classification_requires_agent_and_verifier_success() -> None:
    verified = VerificationResult(True, 0)
    rejected = VerificationResult(False, 1)

    assert classify_trial(
        agent_exit_code=0,
        trace=TraceSummary(reason="model_final"),
        verification=verified,
    ) == "success"
    assert classify_trial(
        agent_exit_code=0,
        trace=TraceSummary(reason="model_final"),
        verification=rejected,
    ) == "incorrect_solution"
    assert classify_trial(
        agent_exit_code=1,
        trace=TraceSummary(reason="api_fatal_error"),
        verification=rejected,
    ) == "provider_failure"
    assert classify_trial(
        agent_exit_code=1,
        trace=TraceSummary(reason="max_tool_calls"),
        verification=rejected,
    ) == "agent_budget_exhausted"


def test_reporter_writes_json_and_markdown(tmp_path) -> None:
    result = TrialResult(
        schema_version=1,
        trial_id="date-01",
        task_id="date_boundary",
        task_title="日期边界",
        category="bug_fix",
        repeat_index=1,
        started_at="2026-08-28T00:00:00+00:00",
        model_requested="deepseek-v4-flash",
        agent_exit_code=0,
        trace=TraceSummary(
            status="model_finished",
            reason="model_final",
            model_calls=2,
            tool_calls=3,
            usage={"total_tokens": 100},
            duration_ms=1500,
        ),
        workspace=WorkspaceChanges(modified=("src/example.py",)),
        verification=VerificationResult(
            True,
            0,
            (CheckResult("hidden behavior", True, "ok"),),
        ),
        classification="success",
        template_digest="abc",
    )

    json_path, markdown_path = BenchmarkReporter().write_summary(
        tmp_path,
        [result],
        model="deepseek-v4-flash",
        source_commit="commit",
        source_dirty=False,
    )

    assert json.loads(json_path.read_text(encoding="utf-8"))["verified_success_rate"] == 1.0
    assert "1/1" in markdown_path.read_text(encoding="utf-8")
