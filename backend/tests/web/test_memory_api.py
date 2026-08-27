from __future__ import annotations

from contextlib import closing
import sqlite3
import time
from pathlib import Path
import threading

from fastapi.testclient import TestClient
import pytest

from coding_agent.config import AppSettings
from coding_agent.core import AgentStatus, RunResult, TerminationReason, TokenUsage
from coding_agent.main import create_app
from coding_agent.memory import MemoryRepository, MemoryService, MemorySummary
from coding_agent.runs import agent_runner as runner_module
from coding_agent.runs.agent_runner import RunOutcome
from coding_agent.security import WorkspacePolicy


class ImmediateRunner:
    ready = True
    model = "fake-deepseek"

    def run(self, spec, *, cancel_event, confirm_command, trace):
        return RunOutcome(
            status="model_finished",
            reason="model_final",
            final_content="a result that may be edited before saving",
            model_calls=1,
            tool_calls=0,
            usage={
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 0,
            },
            duration_seconds=0.01,
        )


class SafeMemoryEventRunner(ImmediateRunner):
    def run(self, spec, *, cancel_event, confirm_command, trace):
        trace.emit(
            "memory_loaded",
            run_id=spec.run_id,
            status="loaded",
            loaded_count=1,
            loaded_ids=["safe-memory-id"],
            content="must-never-reach-sse",
        )
        outcome = super().run(
            spec,
            cancel_event=cancel_event,
            confirm_command=confirm_command,
            trace=trace,
        )
        return RunOutcome(
            status=outcome.status,
            reason=outcome.reason,
            final_content=outcome.final_content,
            model_calls=outcome.model_calls,
            tool_calls=outcome.tool_calls,
            usage=outcome.usage,
            duration_seconds=outcome.duration_seconds,
            memory=MemorySummary(
                status="loaded", loaded_count=1, loaded_ids=("safe-memory-id",)
            ),
        )


class BlockingRunner(ImmediateRunner):
    def __init__(self) -> None:
        self.started = threading.Event()

    def run(self, spec, *, cancel_event, confirm_command, trace):
        self.started.set()
        cancel_event.wait(timeout=2)
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


class TerminalOutcomeRunner(ImmediateRunner):
    def __init__(self, outcome_status: str) -> None:
        self.outcome_status = outcome_status

    def run(self, spec, *, cancel_event, confirm_command, trace):
        return RunOutcome(
            status=self.outcome_status,
            reason="test_terminal",
            final_content="partial" if self.outcome_status == "budget_exhausted" else None,
            model_calls=1,
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


class BlockingCreateMemoryService:
    def __init__(self, delegate: MemoryService) -> None:
        self.delegate = delegate
        self.started = threading.Event()
        self.release = threading.Event()

    def create(self, **kwargs):
        self.started.set()
        if not self.release.wait(timeout=3):
            raise RuntimeError("test did not release memory creation")
        return self.delegate.create(**kwargs)

    def __getattr__(self, name):
        return getattr(self.delegate, name)


def _settings(root: Path, data_dir: Path | None = None) -> AppSettings:
    return AppSettings(
        api_key="test-key",
        allowed_root=root,
        data_dir=data_dir or root.parent / f"{root.name}-data",
        model="fake-deepseek",
        trace_enabled=False,
        wall_time_seconds=5,
        api_timeout_seconds=2,
    )


def _wait(client: TestClient, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        payload = client.get(f"/api/v1/runs/{run_id}").json()
        if payload["status"] in {"completed", "failed", "cancelled", "budget_exhausted"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def _wait_idle(client: TestClient, timeout: float = 2) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.get("/api/v1/health").json()["active_runs"] == 0:
            return
        time.sleep(0.005)
    raise AssertionError("run manager did not release the workspace")


def test_memory_crud_disable_delete_and_purge(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = create_app(settings=_settings(tmp_path), runner=ImmediateRunner())

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/memories",
            json={
                "workspace": str(workspace),
                "kind": "decision",
                "content": "Use the FastAPI boundary.",
                "pinned": True,
            },
        )
        assert created.status_code == 201
        entry = created.json()
        assert entry["source"] == "manual"
        assert entry["source_run_id"] is None
        assert entry["enabled"] is True

        listed = client.get("/api/v1/memories", params={"workspace": str(workspace)})
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [entry["id"]]

        disabled = client.patch(
            f"/api/v1/memories/{entry['id']}",
            json={"workspace": str(workspace), "enabled": False, "pinned": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        deleted = client.delete(
            f"/api/v1/memories/{entry['id']}", params={"workspace": str(workspace)}
        )
        assert deleted.status_code == 204
        missing = client.delete(
            f"/api/v1/memories/{entry['id']}", params={"workspace": str(workspace)}
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "memory_not_found"

        for content in ("one", "two"):
            assert client.post(
                "/api/v1/memories",
                json={"workspace": str(workspace), "kind": "note", "content": content},
            ).status_code == 201
        purged = client.post(
            "/api/v1/memories/purge", json={"workspace": str(workspace)}
        )
        assert purged.json() == {"deleted_count": 2}


def test_run_result_source_requires_retained_terminal_run_in_same_workspace(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    app = create_app(settings=_settings(tmp_path), runner=ImmediateRunner())

    with TestClient(app) as client:
        created_run = client.post(
            "/api/v1/runs", json={"workspace": str(first), "task": "produce result"}
        ).json()
        finished = _wait(client, created_run["run_id"])
        assert finished["status"] == "completed"
        final_events = client.get(
            f"/api/v1/runs/{created_run['run_id']}/events"
        )
        assert "event: run.finished" in final_events.text

        saved = client.post(
            "/api/v1/memories",
            json={
                "workspace": str(first),
                "kind": "note",
                "content": "A manually confirmed summary of the result.",
                "pinned": False,
                "source_run_id": created_run["run_id"],
            },
        )
        assert saved.status_code == 201
        assert saved.json()["source"] == "run_result"
        assert saved.json()["source_run_id"] == created_run["run_id"]

        mismatch = client.post(
            "/api/v1/memories",
            json={
                "workspace": str(second),
                "kind": "note",
                "content": "wrong workspace",
                "pinned": False,
                "source_run_id": created_run["run_id"],
            },
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["error"]["code"] == "memory_workspace_mismatch"

        missing = client.post(
            "/api/v1/memories",
            json={
                "workspace": str(first),
                "kind": "note",
                "content": "unknown source",
                "pinned": False,
                "source_run_id": "not-a-retained-run",
            },
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "memory_not_found"


def test_active_run_blocks_all_same_workspace_mutations_but_not_reads_or_other_workspace(
    tmp_path,
):
    workspace = tmp_path / "project"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    runner = BlockingRunner()
    app = create_app(settings=_settings(tmp_path), runner=runner)

    with TestClient(app) as client:
        seed = client.post(
            "/api/v1/memories",
            json={"workspace": str(workspace), "kind": "note", "content": "seed"},
        ).json()
        created = client.post(
            "/api/v1/runs", json={"workspace": str(workspace), "task": "wait"}
        ).json()
        assert runner.started.wait(timeout=1)

        listed = client.get("/api/v1/memories", params={"workspace": str(workspace)})
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [seed["id"]]

        blocked = (
            client.post(
                "/api/v1/memories",
                json={"workspace": str(workspace), "kind": "note", "content": "new"},
            ),
            client.patch(
                f"/api/v1/memories/{seed['id']}",
                json={"workspace": str(workspace), "content": "changed"},
            ),
            client.delete(
                f"/api/v1/memories/{seed['id']}",
                params={"workspace": str(workspace)},
            ),
            client.post(
                "/api/v1/memories/purge", json={"workspace": str(workspace)}
            ),
        )
        for response in blocked:
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "memory_workspace_busy"

        cross_workspace = client.post(
            "/api/v1/memories",
            json={"workspace": str(other), "kind": "note", "content": "allowed"},
        )
        assert cross_workspace.status_code == 201

        client.post(f"/api/v1/runs/{created['run_id']}/cancel")
        assert _wait(client, created["run_id"])["status"] == "cancelled"
        _wait_idle(client)
        released = client.patch(
            f"/api/v1/memories/{seed['id']}",
            json={"workspace": str(workspace), "content": "changed after run"},
        )
        assert released.status_code == 200


def test_api_mutation_reservation_blocks_run_and_still_allows_list(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    database = tmp_path.parent / f"{tmp_path.name}-blocking-memory.db"
    repository = MemoryRepository(database)
    repository.initialize()
    delegate = MemoryService(repository, WorkspacePolicy(tmp_path))
    blocking_service = BlockingCreateMemoryService(delegate)
    app = create_app(
        settings=_settings(tmp_path),
        runner=ImmediateRunner(),
        memory_service=blocking_service,
    )
    mutation_response: list[object] = []

    with TestClient(app) as client:
        def create_memory() -> None:
            mutation_response.append(
                client.post(
                    "/api/v1/memories",
                    json={
                        "workspace": str(workspace),
                        "kind": "note",
                        "content": "confirmed write",
                    },
                )
            )

        thread = threading.Thread(target=create_memory)
        try:
            thread.start()
            assert blocking_service.started.wait(timeout=1)

            blocked_run = client.post(
                "/api/v1/runs",
                json={"workspace": str(workspace), "task": "must wait for mutation"},
            )
            assert blocked_run.status_code == 409
            assert blocked_run.json()["error"]["code"] == "memory_mutation_in_progress"

            listed = client.get(
                "/api/v1/memories", params={"workspace": str(workspace)}
            )
            assert listed.status_code == 200
            assert listed.json() == {"items": []}
        finally:
            blocking_service.release.set()
            thread.join(timeout=3)

        assert not thread.is_alive()
        assert len(mutation_response) == 1
        assert mutation_response[0].status_code == 201

        run = client.post(
            "/api/v1/runs",
            json={"workspace": str(workspace), "task": "reservation released"},
        ).json()
        assert _wait(client, run["run_id"])["status"] == "completed"


@pytest.mark.parametrize(
    ("outcome_status", "web_status"),
    [
        ("cancelled", "cancelled"),
        ("failed", "failed"),
        ("budget_exhausted", "budget_exhausted"),
    ],
)
def test_only_completed_run_is_eligible_memory_provenance(
    tmp_path, outcome_status, web_status
):
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = create_app(
        settings=_settings(tmp_path), runner=TerminalOutcomeRunner(outcome_status)
    )

    with TestClient(app) as client:
        run = client.post(
            "/api/v1/runs", json={"workspace": str(workspace), "task": "terminal"}
        ).json()
        assert _wait(client, run["run_id"])["status"] == web_status
        _wait_idle(client)

        response = client.post(
            "/api/v1/memories",
            json={
                "workspace": str(workspace),
                "kind": "note",
                "content": "must be rejected",
                "source_run_id": run["run_id"],
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "memory_source_run_ineligible"


def test_run_memory_off_and_sse_memory_event_are_safe(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    app = create_app(settings=_settings(tmp_path), runner=SafeMemoryEventRunner())

    with TestClient(app) as client:
        disabled_run = client.post(
            "/api/v1/runs",
            json={"workspace": str(workspace), "task": "no memory", "use_memory": False},
        ).json()
        disabled = _wait(client, disabled_run["run_id"])
        assert disabled["memory"] == {
            "status": "disabled",
            "loaded_count": 0,
            "loaded_ids": [],
        }

        enabled_run = client.post(
            "/api/v1/runs",
            json={"workspace": str(workspace), "task": "use memory", "use_memory": True},
        ).json()
        enabled = _wait(client, enabled_run["run_id"])
        assert enabled["memory"]["status"] == "loaded"
        events = client.get(f"/api/v1/runs/{enabled_run['run_id']}/events")
        assert "event: memory.loaded" in events.text
        assert "safe-memory-id" in events.text
        assert "must-never-reach-sse" not in events.text
        memory_frame = events.text.split("event: memory.loaded", 1)[1].split("\n\n", 1)[0]
        assert '"run_id"' not in memory_frame
        assert '"content"' not in memory_frame


def test_unavailable_store_degrades_crud_but_not_runs(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    blocked_data_dir = tmp_path.parent / f"{tmp_path.name}-blocked-data-dir"
    blocked_data_dir.write_text("not a directory", encoding="utf-8")
    app = create_app(
        settings=_settings(tmp_path, blocked_data_dir), runner=ImmediateRunner()
    )

    with TestClient(app) as client:
        memories = client.get(
            "/api/v1/memories", params={"workspace": str(workspace)}
        )
        assert memories.status_code == 503
        assert memories.json()["error"]["code"] == "memory_store_unavailable"

        created = client.post(
            "/api/v1/runs", json={"workspace": str(workspace), "task": "still run"}
        ).json()
        finished = _wait(client, created["run_id"])
        assert finished["status"] == "completed"
        assert finished["memory"]["status"] == "unavailable"


def test_corrupted_row_returns_503_and_run_degrades_without_content_leak(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "project"
    workspace.mkdir()

    class FakeAdapter:
        def __init__(self, **kwargs):
            self.model = kwargs["model"]

    class FakeRegistry:
        def __init__(self, workspace, **kwargs):
            pass

    class FakeAgent:
        def __init__(self, adapter, registry, **kwargs):
            pass

        def run(self, task):
            return RunResult(
                run_id="run-id",
                status=AgentStatus.MODEL_FINISHED,
                reason=TerminationReason.MODEL_FINAL,
                final_content="done",
                messages=(),
                model_calls=1,
                tool_calls=0,
                usage=TokenUsage(total_tokens=1),
                duration_seconds=0.01,
            )

    monkeypatch.setattr(runner_module, "DeepSeekAdapter", FakeAdapter)
    monkeypatch.setattr(runner_module, "ToolRegistry", FakeRegistry)
    monkeypatch.setattr(runner_module, "Agent", FakeAgent)
    app = create_app(settings=_settings(tmp_path))

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/memories",
            json={
                "workspace": str(workspace),
                "kind": "note",
                "content": "CORRUPTED_API_SECRET",
            },
        ).json()
        database = client.app.state.memory_service.repository.database_path
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(
                "UPDATE memory_entries SET updated_at = ? WHERE id = ?",
                ("invalid-CORRUPTED_API_SECRET", created["id"]),
            )

        listed = client.get(
            "/api/v1/memories", params={"workspace": str(workspace)}
        )
        assert listed.status_code == 503
        assert listed.json()["error"]["code"] == "memory_store_unavailable"
        assert "CORRUPTED_API_SECRET" not in listed.text

        run = client.post(
            "/api/v1/runs", json={"workspace": str(workspace), "task": "still execute"}
        ).json()
        finished = _wait(client, run["run_id"])
        assert finished["status"] == "completed"
        assert finished["memory"]["status"] == "unavailable"
        events = client.get(f"/api/v1/runs/{run['run_id']}/events")
        assert "CORRUPTED_API_SECRET" not in events.text


def test_explicit_test_data_dir_never_uses_user_default(tmp_path, monkeypatch):
    sentinel_default = tmp_path / "must-not-be-created"
    monkeypatch.setenv("LOCALAPPDATA", str(sentinel_default))
    workspace = tmp_path / "project"
    workspace.mkdir()
    explicit = tmp_path.parent / f"{tmp_path.name}-isolated-test-data"
    app = create_app(
        settings=_settings(tmp_path, explicit), runner=ImmediateRunner()
    )

    with TestClient(app):
        assert (explicit / "coding-agent.db").is_file()
    assert not sentinel_default.exists()
