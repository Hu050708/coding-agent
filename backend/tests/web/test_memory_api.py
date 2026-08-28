"""验证项目记忆 HTTP 接口的增删改查和错误响应。"""

from __future__ import annotations

from uuid import uuid4

from tests.web.test_api import (
    BlockingRunner,
    ImmediateRunner,
    _client,
    _create_conversation,
    _create_run,
    _register_workspace,
    _wait_status,
)


def _create_memory(client, workspace_id: str, **overrides) -> dict:
    payload = {
        "kind": "note",
        "content": "Use the repository's existing test conventions.",
        "pinned": False,
        **overrides,
    }
    response = client.post(f"/api/v1/workspaces/{workspace_id}/memories", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_memory_crud_clear_and_cross_workspace_ids_are_scoped(tmp_path):
    with _client(tmp_path, ImmediateRunner()) as (client, root):
        first = _register_workspace(client, root, "first")
        second = _register_workspace(client, root, "second")

        assert client.get(f"/api/v1/workspaces/{first['id']}/memories").json() == {
            "items": []
        }
        memory = _create_memory(
            client,
            first["id"],
            kind="preference",
            content="Run focused tests before the full suite.",
        )
        assert memory["source"] == "manual"
        assert memory["workspace_id"] == first["id"]

        updated = client.patch(
            f"/api/v1/workspaces/{first['id']}/memories/{memory['id']}",
            json={"content": "Run focused tests, then the full suite.", "pinned": True},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["pinned"] is True

        hidden = client.patch(
            f"/api/v1/workspaces/{second['id']}/memories/{memory['id']}",
            json={"enabled": False},
        )
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "memory_not_found"
        assert (
            client.delete(
                f"/api/v1/workspaces/{second['id']}/memories/{memory['id']}"
            ).status_code
            == 404
        )

        cleared = client.post(f"/api/v1/workspaces/{first['id']}/memories/clear")
        assert cleared.status_code == 200
        assert cleared.json() == {"deleted_count": 1}
        assert client.get(f"/api/v1/workspaces/{first['id']}/memories").json() == {
            "items": []
        }


def test_completed_run_can_be_confirmed_as_memory_with_workspace_provenance(tmp_path):
    with _client(tmp_path, ImmediateRunner()) as (client, root):
        first = _register_workspace(client, root, "first")
        second = _register_workspace(client, root, "second")
        conversation = _create_conversation(client, first["id"])
        run = _create_run(client, conversation["id"])
        _wait_status(client, run["id"], {"completed"})

        confirmed = _create_memory(
            client,
            first["id"],
            kind="decision",
            content="The user confirmed this run result as durable memory.",
            source_run_id=run["id"],
        )
        assert confirmed["source"] == "run_result"
        assert confirmed["source_run_id"] == run["id"]

        mismatch = client.post(
            f"/api/v1/workspaces/{second['id']}/memories",
            json={
                "kind": "decision",
                "content": "Must not cross workspace boundaries.",
                "source_run_id": run["id"],
            },
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["error"]["code"] == "source_run_workspace_mismatch"

        missing = client.post(
            f"/api/v1/workspaces/{first['id']}/memories",
            json={
                "kind": "decision",
                "content": "Unknown provenance must not be accepted.",
                "source_run_id": str(uuid4()),
            },
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "source_run_not_found"


def test_active_run_freezes_its_workspace_memory_but_not_other_workspaces(tmp_path):
    runner = BlockingRunner()
    with _client(tmp_path, runner) as (client, root):
        first = _register_workspace(client, root, "first")
        second = _register_workspace(client, root, "second")
        memory = _create_memory(client, first["id"])
        conversation = _create_conversation(client, first["id"])
        run = _create_run(client, conversation["id"])
        assert runner.started.wait(1)

        blocked_requests = (
            client.post(
                f"/api/v1/workspaces/{first['id']}/memories",
                json={"kind": "note", "content": "blocked create"},
            ),
            client.patch(
                f"/api/v1/workspaces/{first['id']}/memories/{memory['id']}",
                json={"pinned": True},
            ),
            client.delete(
                f"/api/v1/workspaces/{first['id']}/memories/{memory['id']}"
            ),
            client.post(f"/api/v1/workspaces/{first['id']}/memories/clear"),
        )
        for response in blocked_requests:
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == "memory_workspace_busy"

        other = _create_memory(
            client,
            second["id"],
            content="A different workspace remains independently mutable.",
        )
        assert other["workspace_id"] == second["id"]

        runner.release.set()
        _wait_status(client, run["id"], {"completed"})
        assert (
            client.patch(
                f"/api/v1/workspaces/{first['id']}/memories/{memory['id']}",
                json={"pinned": True},
            ).status_code
            == 200
        )
