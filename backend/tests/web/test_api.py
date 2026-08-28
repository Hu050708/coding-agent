"""验证 HTTP 运行接口、审批接口和 SSE 事件续传。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from coding_agent.settings import AppSettings
from coding_agent.agents.memory import MemorySummary
from coding_agent.database import create_database
from coding_agent.models import Base
from coding_agent.repository import PersistenceService
from coding_agent.main import create_app
from coding_agent.agents.runtime.agent_runner import RunOutcome
from coding_agent.agents.security import ToolApprovalRequest


class ImmediateRunner:
    ready = True
    model = "test-model"

    def run(self, spec, *, cancel_event, confirm_command, trace):
        trace.emit("tool_started", run_id=spec.run_id, sequence=1, tool="read_file")
        trace.emit(
            "tool_completed",
            run_id=spec.run_id,
            sequence=1,
            tool="read_file",
            ok=True,
            error_code=None,
            exit_code=None,
            duration_ms=1,
            truncated=False,
        )
        return RunOutcome(
            status="model_finished",
            reason="verified_completion",
            final_content="done",
            model_calls=1,
            tool_calls=1,
            usage={
                "prompt_tokens": 8,
                "completion_tokens": 2,
                "total_tokens": 10,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 8,
            },
            duration_seconds=0.01,
            memory=MemorySummary(status="loaded" if spec.memory_snapshot else "empty"),
        )


class NotReadyRunner(ImmediateRunner):
    ready = False


class ApprovalRunner(ImmediateRunner):
    def run(self, spec, *, cancel_event, confirm_command, trace):
        request = ToolApprovalRequest(
            tool_name="run_command",
            action_summary="python (3 arguments)",
            argv=(sys.executable, "-m", "pytest", "-q"),
            cwd=str(spec.workspace),
            reason="This command requires one-time approval.",
        )
        approved = confirm_command(request)
        return RunOutcome(
            status="model_finished" if approved else "cancelled",
            reason="verified_completion" if approved else "user_cancelled",
            final_content="approved" if approved else None,
            model_calls=1,
            tool_calls=1,
            usage={},
            duration_seconds=0.01,
            memory=MemorySummary(status="empty"),
        )


class BlockingRunner(ImmediateRunner):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, spec, *, cancel_event, confirm_command, trace):
        self.started.set()
        while not self.release.wait(0.01):
            if cancel_event.is_set():
                return RunOutcome(
                    status="cancelled",
                    reason="user_cancelled",
                    final_content=None,
                    model_calls=0,
                    tool_calls=0,
                    usage={},
                    duration_seconds=0.01,
                    memory=MemorySummary(status="empty"),
                )
        return super().run(
            spec,
            cancel_event=cancel_event,
            confirm_command=confirm_command,
            trace=trace,
        )


@contextmanager
def _client(tmp_path: Path, runner):
    allowed_root = tmp_path / "workspaces"
    allowed_root.mkdir()
    data_dir = tmp_path / "private-data"
    settings = AppSettings(
        api_key="test-key" if runner.ready else "",
        allowed_root=allowed_root,
        data_dir=data_dir,
        trace_enabled=False,
        max_active_runs=4,
    )
    database = create_database(
        f"sqlite+pysqlite:///{(tmp_path / 'web.db').as_posix()}",
        require_postgresql=False,
    )
    Base.metadata.create_all(database.engine)
    persistence = PersistenceService(database.session_factory)
    app = create_app(
        settings=settings,
        runner=runner,
        database=database,
        persistence=persistence,
        migrate_database=False,
    )
    try:
        with TestClient(app) as client:
            yield client, allowed_root
    finally:
        database.dispose()


def _register_workspace(client: TestClient, root: Path, name: str = "project") -> dict:
    path = root / name
    path.mkdir()
    response = client.post(
        "/api/v1/workspaces", json={"path": str(path), "display_name": name.title()}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_conversation(client: TestClient, workspace_id: str) -> dict:
    response = client.post(
        "/api/v1/conversations",
        json={
            "workspace_id": workspace_id,
            "default_permission_mode": "agent",
            "use_memory": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_run(
    client: TestClient,
    conversation_id: str,
    *,
    content: str = "finish the task",
    permission_mode: str = "agent",
    request_id: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/runs",
        json={
            "content": content,
            "permission_mode": permission_mode,
            "use_memory": True,
            "client_request_id": request_id or str(uuid4()),
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def _wait_status(client: TestClient, run_id: str, statuses: set[str]) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"run did not reach {statuses}")


def test_health_workspace_conversation_run_messages_and_sse(tmp_path):
    with _client(tmp_path, ImmediateRunner()) as (client, root):
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["database"] == "ready"
        assert health.json()["provider_configured"] is True

        browse = client.get("/api/v1/workspaces/browse")
        assert browse.status_code == 200
        assert browse.json()["current_path"] == str(root.resolve())

        workspace = _register_workspace(client, root)
        conversation = _create_conversation(client, workspace["id"])
        created = _create_run(client, conversation["id"], permission_mode="ask")
        terminal = _wait_status(client, created["id"], {"completed"})

        assert terminal["final_content"] == "done"
        assert terminal["permission_mode"] == "ask"
        messages = client.get(
            f"/api/v1/conversations/{conversation['id']}/messages"
        ).json()["items"]
        assert [(item["role"], item["content"]) for item in messages] == [
            ("user", "finish the task"),
            ("assistant", "done"),
        ]

        stream = client.get(f"/api/v1/runs/{created['id']}/events?after_seq=0")
        assert stream.status_code == 200
        assert "event: run.accepted" in stream.text
        assert "event: tool.completed" in stream.text
        assert "event: run.finished" in stream.text
        assert "finish the task" not in stream.text


def test_approval_is_live_but_persisted_replay_drops_argv_and_cwd(tmp_path):
    with _client(tmp_path, ApprovalRunner()) as (client, root):
        workspace = _register_workspace(client, root)
        conversation = _create_conversation(client, workspace["id"])
        run = _create_run(client, conversation["id"])
        waiting = _wait_status(client, run["id"], {"waiting_approval"})
        approval = waiting["pending_approval"]

        assert approval["argv"][:3] == [sys.executable, "-m", "pytest"]
        decision = client.post(
            f"/api/v1/runs/{run['id']}/approvals/{approval['id']}",
            json={"decision": "approve"},
        )
        assert decision.status_code == 200, decision.text
        terminal = _wait_status(client, run["id"], {"completed"})
        assert terminal["final_content"] == "approved"

        replay = client.get(f"/api/v1/runs/{run['id']}/events").text
        assert "approval.required" in replay
        assert sys.executable not in replay
        assert str(root) not in replay


def test_same_workspace_is_serial_but_different_workspaces_run_concurrently(tmp_path):
    runner = BlockingRunner()
    with _client(tmp_path, runner) as (client, root):
        first = _register_workspace(client, root, "first")
        second = _register_workspace(client, root, "second")
        first_conversation = _create_conversation(client, first["id"])
        other_first_conversation = _create_conversation(client, first["id"])
        second_conversation = _create_conversation(client, second["id"])

        first_run = _create_run(client, first_conversation["id"])
        assert runner.started.wait(1)
        busy = client.post(
            f"/api/v1/conversations/{other_first_conversation['id']}/runs",
            json={
                "content": "must be rejected",
                "permission_mode": "agent",
                "use_memory": False,
                "client_request_id": str(uuid4()),
            },
        )
        assert busy.status_code == 409
        assert busy.json()["error"]["code"] == "workspace_busy"

        second_run = _create_run(client, second_conversation["id"])
        assert second_run["workspace_id"] == second["id"]
        runner.release.set()
        _wait_status(client, first_run["id"], {"completed"})
        _wait_status(client, second_run["id"], {"completed"})


def test_unconfigured_provider_does_not_persist_user_message(tmp_path):
    with _client(tmp_path, NotReadyRunner()) as (client, root):
        workspace = _register_workspace(client, root)
        conversation = _create_conversation(client, workspace["id"])
        health = client.get("/api/v1/health").json()
        assert health["status"] == "degraded"
        assert health["provider_configured"] is False

        response = client.post(
            f"/api/v1/conversations/{conversation['id']}/runs",
            json={
                "content": "private task that must not be reflected",
                "permission_mode": "workspace_full",
                "use_memory": True,
                "client_request_id": str(uuid4()),
            },
        )
        assert response.status_code == 503
        assert "private task" not in response.text
        messages = client.get(
            f"/api/v1/conversations/{conversation['id']}/messages"
        ).json()["items"]
        assert messages == []


def test_invalid_ids_and_nonlocal_origins_are_rejected_without_500(tmp_path):
    with _client(tmp_path, ImmediateRunner()) as (client, root):
        assert client.get("/api/v1/runs/not-a-uuid").status_code == 422
        assert (
            client.get("/api/v1/conversations", params={"workspace_id": "bad"}).status_code
            == 422
        )
        blocked = client.post(
            "/api/v1/workspaces",
            json={"path": str(root)},
            headers={"Origin": "https://example.com"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "origin_not_allowed"


def test_terminal_persistence_is_reconciled_after_callback_failures(tmp_path):
    runner = BlockingRunner()
    with _client(tmp_path, runner) as (client, root):
        workspace = _register_workspace(client, root)
        conversation = _create_conversation(client, workspace["id"])
        run = _create_run(client, conversation["id"])
        assert runner.started.wait(1)

        persistence = client.app.state.persistence
        original_finish = persistence.append_assistant_message_and_finish
        attempts = 0

        def flaky_finish(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise OSError("simulated transient database failure")
            return original_finish(*args, **kwargs)

        persistence.append_assistant_message_and_finish = flaky_finish
        runner.release.set()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if client.app.state.run_manager.get(run["id"])["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("in-memory run did not finish")

    # 两个正常终态回调均失败，因此 PostgreSQL 仍投影为活动运行，
    # 直到公共读取入口执行显式对账。
        assert persistence.get_run(run["id"]).status in {"running", "starting"}
        repaired = client.get(f"/api/v1/runs/{run['id']}")
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()["status"] == "completed"
        assert attempts >= 3

    # 修复后的终态记录不再阻塞工作区唯一活动运行约束。
        next_run = _create_run(client, conversation["id"], content="run after repair")
        _wait_status(client, next_run["id"], {"completed"})


def test_terminal_sse_drains_every_durable_page_before_closing(tmp_path):
    with _client(tmp_path, ImmediateRunner()) as (client, root):
        workspace = _register_workspace(client, root)
        conversation = _create_conversation(client, workspace["id"])
        run = _create_run(client, conversation["id"])
        _wait_status(client, run["id"], {"completed"})

        service = client.app.state.services.runs
        original_event_records = service.event_records

        def two_at_a_time(run_id: str, *, after_seq: int = 0):
            return original_event_records(run_id, after_seq=after_seq)[:2]

        service.event_records = two_at_a_time
        stream = client.get(f"/api/v1/runs/{run['id']}/events?after_seq=0")
        assert stream.status_code == 200
        assert "event: run.accepted" in stream.text
        assert "event: run.finished" in stream.text
