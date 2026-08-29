"""验证评测结果 API 只返回安全 summary 数据。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from coding_agent.router.errors import install_error_handlers
from coding_agent.router.evaluations import router
from coding_agent.services import EvaluationReportService


def _summary() -> dict[str, object]:
    return {
        "schema_version": 1,
        "model_requested": "deepseek-v4-flash",
        "source_commit": "abc123",
        "source_dirty": False,
        "total_trials": 0,
        "verified_successes": 0,
        "verified_success_rate": 0.0,
        "classifications": {},
        "duration_seconds": {"mean": 0.0, "median": 0.0, "maximum": 0.0},
        "total_tokens": {"mean": 0.0, "median": 0.0, "maximum": 0.0},
        "tasks": {},
        "trials": [],
    }


def test_evaluation_api_lists_and_reads_summary(tmp_path) -> None:
    root = tmp_path / "benchmark-runs"
    run = root / "formal-3x3"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps(_summary()), encoding="utf-8")
    app = FastAPI()
    app.state.services = SimpleNamespace(evaluations=EvaluationReportService(root))
    install_error_handlers(app)
    app.include_router(router, prefix="/api/v1")

    with TestClient(app) as client:
        listed = client.get("/api/v1/evaluations")
        detail = client.get("/api/v1/evaluations/formal-3x3")
        missing = client.get("/api/v1/evaluations/missing")

    assert listed.status_code == 200
    assert listed.json()["runs"][0]["run_id"] == "formal-3x3"
    assert detail.status_code == 200
    assert detail.json()["model_requested"] == "deepseek-v4-flash"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "evaluation_run_not_found"
