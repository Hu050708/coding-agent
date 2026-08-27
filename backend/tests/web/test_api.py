from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from clearloop.config import AppSettings
from clearloop.main import create_app
from clearloop.runs.agent_runner import RunOutcome, RunSpec
from clearloop.security import CommandDecision, CommandRequest


class ImmediateRunner:
    ready = True
    model = "fake-deepseek"

    def run(self, spec, *, cancel_event, confirm_command, trace):
        trace.emit(
            "model_completed",
            run_id=spec.run_id,
            sequence=1,
            model=self.model,
            response_model=self.model,
            finish_reason="stop",
            latency_ms=1,
            usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            retry_count=0,
        )
        return RunOutcome(
            status="model_finished",
            reason="model_final",
            final_content="done",
            model_calls=1,
            tool_calls=0,
            usage={
                "prompt_tokens": 2,
                "completion_tokens": 3,
                "total_tokens": 5,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 0,
            },
            duration_seconds=0.01,
        )


class ApprovalRunner:
    ready = True
    model = "fake-deepseek"

    def run(self, spec: RunSpec, *, cancel_event, confirm_command, trace):
        request = CommandRequest(
            argv=("python", "-c", "print('safe test')"),
            resolved_argv=("python", "-c", "print('safe test')"),
            cwd=spec.workspace,
            decision=CommandDecision.CONFIRM,
            reason="Test confirmation is required.",
        )
        approved = confirm_command(request)
        return RunOutcome(
            status="cancelled" if cancel_event.is_set() else "model_finished",
            reason="user_cancelled" if cancel_event.is_set() else "model_final",
            final_content="approved" if approved else "rejected",
            model_calls=1,
            tool_calls=1,
            usage={
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 0,
            },
            duration_seconds=0.01,
        )


class BlockingRunner:
    ready = True
    model = "fake-deepseek"

    def __init__(self) -> None:
        self.started = threading.Event()

    def run(self, spec, *, cancel_event, confirm_command, trace):
        self.started.set()
        cancel_event.wait(timeout=3)
        return RunOutcome(
            status="cancelled" if cancel_event.is_set() else "failed",
            reason="user_cancelled" if cancel_event.is_set() else "test_timeout",
            final_content=None,
            model_calls=0,
            tool_calls=0,
            usage={
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 0,
            },
            duration_seconds=0.01,
        )


class NotReadyRunner:
    ready = False
    model = "fake-deepseek"

    def run(self, spec, *, cancel_event, confirm_command, trace):  # pragma: no cover
        raise AssertionError("an unconfigured runner must not be started")


def _settings(root: Path) -> AppSettings:
    return AppSettings(
        api_key="server-test-key",
        allowed_root=root,
        data_dir=root.parent / f"{root.name}-data",
        model="fake-deepseek",
        trace_enabled=False,
        approval_timeout_seconds=2,
        wall_time_seconds=5,
        api_timeout_seconds=2,
    )


def _wait_for(client: TestClient, run_id: str, expected: set[str], timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in expected:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"run did not reach {expected}")


def test_health_workspace_run_status_and_sse_contract(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = create_app(settings=_settings(tmp_path), runner=ImmediateRunner())

    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "service": "clearloop-web",
            "api_key_configured": True,
            "model": "fake-deepseek",
            "allowed_root": str(tmp_path.resolve()),
            "max_active_runs": 1,
            "active_runs": 0,
            "max_model_calls": 16,
            "max_tool_calls": 40,
            "max_total_tokens": 200_000,
            "wall_time_seconds": 5.0,
        }

        validation = client.post(
            "/api/v1/workspaces/validate", json={"workspace": str(workspace)}
        )
        assert validation.status_code == 200
        assert validation.json()["valid"] is True

        created = client.post(
            "/api/v1/runs",
            json={"workspace": str(workspace), "task": "do not echo this private task"},
        )
        assert created.status_code == 202
        run_id = created.json()["run_id"]
        finished = _wait_for(client, run_id, {"completed"})
        assert finished["final_content"] == "done"
        assert finished["usage"]["total_tokens"] == 5
        assert "messages" not in finished

        events = client.get(f"/api/v1/runs/{run_id}/events")
        assert events.status_code == 200
        assert "event: run.accepted" in events.text
        assert "event: run.started" in events.text
        assert "event: model.completed" in events.text
        assert "event: run.finished" in events.text
        assert "do not echo this private task" not in events.text
        assert "server-test-key" not in events.text
        assert '"finish_reason":"stop"' in events.text

        replay = client.get(
            f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "2"}
        )
        assert replay.status_code == 200
        assert "id: 1\n" not in replay.text
        assert "id: 2\n" not in replay.text


def test_approval_can_be_resolved_once(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = create_app(settings=_settings(tmp_path), runner=ApprovalRunner())

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/runs", json={"workspace": str(workspace), "task": "request approval"}
        )
        run_id = created.json()["run_id"]
        waiting = _wait_for(client, run_id, {"waiting_approval"})
        approval = waiting["pending_approval"]
        assert approval["argv"][:2] == ["python", "-c"]

        accepted = client.post(
            f"/api/v1/runs/{run_id}/approvals/{approval['approval_id']}",
            json={"decision": "approve"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] is True
        finished = _wait_for(client, run_id, {"completed"})
        assert finished["final_content"] == "approved"
        assert finished["pending_approval"] is None

        duplicate = client.post(
            f"/api/v1/runs/{run_id}/approvals/{approval['approval_id']}",
            json={"decision": "approve"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "approval_not_pending"


def test_cancel_wakes_pending_approval_and_is_idempotent(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = create_app(settings=_settings(tmp_path), runner=ApprovalRunner())

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/runs", json={"workspace": str(workspace), "task": "request approval"}
        )
        run_id = created.json()["run_id"]
        _wait_for(client, run_id, {"waiting_approval"})

        cancelling = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert cancelling.status_code == 202
        assert cancelling.json()["status"] in {"cancelling", "cancelled"}
        finished = _wait_for(client, run_id, {"cancelled"})
        assert finished["cancel_requested"] is True
        assert finished["pending_approval"] is None

        repeated = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert repeated.status_code == 202
        assert repeated.json()["status"] == "cancelled"

        events = client.get(f"/api/v1/runs/{run_id}/events")
        assert '"event":"approval.resolved"' in events.text
        assert '"decision":"reject"' in events.text
        assert '"resolution":"cancelled"' in events.text


def test_capacity_and_workspace_lock_are_enforced(tmp_path):
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()
    runner = BlockingRunner()
    app = create_app(settings=_settings(tmp_path), runner=runner)

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/runs", json={"workspace": str(first_workspace), "task": "wait"}
        )
        run_id = first.json()["run_id"]
        assert runner.started.wait(timeout=1)

        same_workspace = client.post(
            "/api/v1/runs", json={"workspace": str(first_workspace), "task": "second"}
        )
        assert same_workspace.status_code == 409
        assert same_workspace.json()["error"]["code"] == "workspace_busy"

        at_capacity = client.post(
            "/api/v1/runs", json={"workspace": str(second_workspace), "task": "second"}
        )
        assert at_capacity.status_code == 429
        assert at_capacity.json()["error"]["code"] == "run_capacity_reached"
        client.post(f"/api/v1/runs/{run_id}/cancel")
        _wait_for(client, run_id, {"cancelled"})


def test_errors_do_not_reflect_task_or_secret_and_origin_is_local(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = create_app(settings=_settings(tmp_path), runner=ImmediateRunner())

    with TestClient(app) as client:
        invalid = client.post(
            "/api/v1/runs", json={"workspace": str(workspace), "task": "   "}
        )
        assert invalid.status_code == 422
        assert "server-test-key" not in invalid.text
        assert '"   "' not in invalid.text

        blocked = client.post(
            "/api/v1/workspaces/validate",
            json={"workspace": str(workspace)},
            headers={"Origin": "https://example.com"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "origin_not_allowed"

        missing = client.get("/api/v1/runs/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "run_not_found"


def test_unconfigured_provider_is_degraded_and_cannot_start_run(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    settings = AppSettings(
        api_key="",
        allowed_root=tmp_path,
        data_dir=tmp_path.parent / f"{tmp_path.name}-data",
        model="fake-deepseek",
        trace_enabled=False,
    )
    app = create_app(settings=settings, runner=NotReadyRunner())

    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        assert health.json()["api_key_configured"] is False

        response = client.post(
            "/api/v1/runs", json={"workspace": str(workspace), "task": "must not run"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_not_configured"
