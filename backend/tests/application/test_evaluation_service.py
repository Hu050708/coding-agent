"""验证 benchmark 报告只读服务的目录和错误边界。"""

from __future__ import annotations

import json

import pytest

from coding_agent.services import ApplicationError, EvaluationReportService


def _summary() -> dict[str, object]:
    return {
        "schema_version": 1,
        "model_requested": "deepseek-v4-flash",
        "source_commit": "abc123",
        "source_dirty": False,
        "total_trials": 1,
        "verified_successes": 1,
        "verified_success_rate": 1.0,
        "classifications": {"success": 1},
        "duration_seconds": {"mean": 4.0, "median": 4.0, "maximum": 4.0},
        "total_tokens": {"mean": 100.0, "median": 100.0, "maximum": 100.0},
        "tasks": {},
        "trials": [],
    }


def test_evaluation_service_lists_and_reads_detail(tmp_path) -> None:
    root = tmp_path / "runs"
    older = root / "formal-older"
    latest = root / "formal-latest"
    older.mkdir(parents=True)
    latest.mkdir()
    (older / "summary.json").write_text(json.dumps(_summary()), encoding="utf-8")
    (latest / "summary.json").write_text(json.dumps(_summary()), encoding="utf-8")

    service = EvaluationReportService(root)
    items = service.list_runs()

    assert {item["run_id"] for item in items} == {"formal-older", "formal-latest"}
    assert service.get_run("formal-latest")["verified_successes"] == 1


def test_evaluation_service_rejects_unknown_and_traversal_ids(tmp_path) -> None:
    service = EvaluationReportService(tmp_path / "runs")

    for run_id in ("missing", "../outside", ""):
        with pytest.raises(ApplicationError) as exc_info:
            service.get_run(run_id)
        assert exc_info.value.code == "evaluation_run_not_found"
