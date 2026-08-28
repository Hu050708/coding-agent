"""验证记忆服务的去重、容量、筛选和快照语义。"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
import threading

import pytest

from coding_agent.agents.memory import (
    MemoryKind,
    MemoryRepository,
    MemoryRepositoryError,
    MemoryService,
    MemorySource,
)
from coding_agent.agents.memory import MemoryServiceError
from coding_agent.agents.security import WorkspacePolicy


def _service(tmp_path, *, max_items=500, snapshot_items=8, snapshot_chars=6_000):
    root = tmp_path / "workspaces"
    root.mkdir(exist_ok=True)
    database = tmp_path / "data" / "memory.db"
    repository = MemoryRepository(database)
    repository.initialize()
    return (
        MemoryService(
            repository,
            WorkspacePolicy(root),
            max_items=max_items,
            snapshot_items=snapshot_items,
            snapshot_chars=snapshot_chars,
        ),
        database,
        root,
    )


def test_crud_persists_across_repository_restart_and_closes_connections(tmp_path):
    service, database, root = _service(tmp_path)
    workspace = root / "alpha"
    workspace.mkdir()

    created = service.create(
        workspace=str(workspace),
        kind=MemoryKind.DECISION,
        content="Use FastAPI for the local API.",
        pinned=True,
    )
    assert created.source is MemorySource.MANUAL
    assert created.workspace == os.fspath(workspace.resolve())

    restarted_repository = MemoryRepository(database)
    restarted_repository.initialize()
    restarted = MemoryService(restarted_repository, WorkspacePolicy(root))
    assert [entry.id for entry in restarted.list(str(workspace))] == [created.id]
    with closing(sqlite3.connect(database)) as connection:
        stored_key = connection.execute(
            "SELECT workspace_key FROM memory_entries WHERE id = ?", (created.id,)
        ).fetchone()[0]
    assert stored_key != os.fspath(workspace.resolve())
    assert len(stored_key) == 64

    updated = restarted.update(
        workspace=str(workspace),
        memory_id=created.id,
        kind="preference",
        content="Prefer FastAPI for the local API.",
        pinned=False,
        enabled=False,
    )
    assert updated.kind is MemoryKind.PREFERENCE
    assert updated.enabled is False

    # 在 Windows 上，若增删改查连接泄漏，此重命名会立即失败。
    moved = database.with_suffix(".moved")
    database.rename(moved)
    moved.rename(database)

    restarted.delete(workspace=str(workspace), memory_id=created.id)
    assert restarted.list(str(workspace)) == []


def test_dedup_capacity_and_workspace_isolation(tmp_path):
    # 创建两个工作区，分别验证同工作区内容去重和容量上限。
    service, _database, root = _service(tmp_path, max_items=2)
    first = root / "first"
    second = root / "second"
    first.mkdir()
    second.mkdir()

    first_entry = service.create(
        workspace=str(first), kind="fact", content="  Vue   uses Vite  "
    )
    with pytest.raises(MemoryServiceError) as duplicate:
        service.create(workspace=str(first), kind="note", content="vue uses vite")
    assert duplicate.value.code == "memory_duplicate"

    other_first_entry = service.create(
        workspace=str(first), kind="note", content="A different entry"
    )
    with pytest.raises(MemoryServiceError) as capacity:
        service.create(workspace=str(first), kind="note", content="A third entry")
    assert capacity.value.code == "memory_capacity_reached"

    # 相同内容可存在于不同工作区，且跨工作区 ID 不能用于删除。
    second_entry = service.create(
        workspace=str(second), kind="fact", content="Vue uses Vite"
    )
    assert {entry.id for entry in service.list(str(first))} == {
        first_entry.id,
        other_first_entry.id,
    }
    assert [entry.id for entry in service.list(str(second))] == [second_entry.id]
    with pytest.raises(MemoryServiceError) as isolated:
        service.delete(workspace=str(second), memory_id=first_entry.id)
    assert isolated.value.code == "memory_not_found"


def test_snapshot_is_pinned_relevant_bounded_and_excludes_disabled(tmp_path):
    service, _database, root = _service(
        tmp_path, snapshot_items=3, snapshot_chars=45
    )
    workspace = root / "project"
    workspace.mkdir()

    pinned = service.create(
        workspace=str(workspace),
        kind="decision",
        content="Always keep the API local only.",
        pinned=True,
    )
    relevant = service.create(
        workspace=str(workspace),
        kind="fact",
        content="日期边界测试使用北京时间",
    )
    service.create(
        workspace=str(workspace),
        kind="note",
        content="Unrelated color palette note",
    )
    disabled = service.create(
        workspace=str(workspace),
        kind="preference",
        content="日期边界测试 should be disabled",
    )
    service.update(
        workspace=str(workspace), memory_id=disabled.id, enabled=False
    )

    snapshot = service.snapshot(
        workspace=workspace, task="修复日期边界测试 timezone bug"
    )

    assert snapshot.status == "loaded"
    assert snapshot.entries[0].id == pinned.id
    assert relevant.id in {entry.id for entry in snapshot.entries}
    assert disabled.id not in {entry.id for entry in snapshot.entries}
    assert len(snapshot.entries) <= 3
    assert sum(len(entry.content) for entry in snapshot.entries) <= 45
    assert snapshot.summary.loaded_ids == tuple(entry.id for entry in snapshot.entries)


def test_snapshot_uses_recency_after_equal_pin_and_relevance(tmp_path):
    service, _database, root = _service(tmp_path)
    workspace = root / "project"
    workspace.mkdir()
    older = service.create(workspace=str(workspace), kind="note", content="alpha")
    newer = service.create(workspace=str(workspace), kind="note", content="beta")

    snapshot = service.snapshot(workspace=workspace, task="unrelated task")

    assert [entry.id for entry in snapshot.entries[:2]] == [newer.id, older.id]


def test_content_limit_is_enforced_by_domain_service(tmp_path):
    service, _database, root = _service(tmp_path)
    workspace = root / "project"
    workspace.mkdir()
    assert len(
        service.create(workspace=str(workspace), kind="note", content="x" * 2_000).content
    ) == 2_000
    with pytest.raises(MemoryServiceError) as too_large:
        service.create(workspace=str(workspace), kind="note", content="y" * 2_001)
    assert too_large.value.code == "memory_content_too_large"


def test_purge_and_run_result_provenance_validation(tmp_path):
    service, _database, root = _service(tmp_path)
    workspace = root / "project"
    workspace.mkdir()

    with pytest.raises(MemoryServiceError) as invalid_source:
        service.create(
            workspace=str(workspace),
            kind="note",
            content="candidate",
            source=MemorySource.RUN_RESULT,
            source_run_id=None,
        )
    assert invalid_source.value.code == "memory_source_run_invalid"

    service.create(workspace=str(workspace), kind="fact", content="one")
    service.create(workspace=str(workspace), kind="fact", content="two")
    assert service.purge(workspace=str(workspace)) == 2
    assert service.snapshot(workspace=workspace, task="anything").status == "empty"


def test_concurrent_creates_enforce_capacity_atomically(tmp_path):
    service, _database, root = _service(tmp_path, max_items=1)
    workspace = root / "project"
    workspace.mkdir()
    barrier = threading.Barrier(2)

    def create(content: str) -> str:
        barrier.wait(timeout=2)
        try:
            return service.create(
                workspace=str(workspace), kind="note", content=content
            ).id
        except MemoryServiceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, ("first concurrent entry", "second concurrent entry")))

    assert sum(result == "memory_capacity_reached" for result in results) == 1
    assert len(service.list(str(workspace))) == 1


def test_repository_refuses_unknown_future_schema_without_downgrading(tmp_path):
    database = tmp_path / "future.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA user_version=2")

    with pytest.raises(MemoryRepositoryError, match="unsupported schema"):
        MemoryRepository(database).initialize()

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_create_and_update_materialize_response_inside_write_transaction(
    tmp_path, monkeypatch
):
    service, _database, root = _service(tmp_path)
    workspace = root / "project"
    workspace.mkdir()

    def forbidden_followup_get(*_args, **_kwargs):
        raise AssertionError("a committed DML response must not use a follow-up connection")

    monkeypatch.setattr(service.repository, "get", forbidden_followup_get)
    created = service.create(
        workspace=str(workspace), kind="note", content="created atomically"
    )
    updated = service.update(
        workspace=str(workspace),
        memory_id=created.id,
        content="updated atomically",
    )

    assert created.content == "created atomically"
    assert updated.content == "updated atomically"


def test_concurrent_updates_each_return_their_own_committed_value(tmp_path):
    service, _database, root = _service(tmp_path)
    workspace = root / "project"
    workspace.mkdir()
    entry = service.create(workspace=str(workspace), kind="note", content="initial")
    barrier = threading.Barrier(2)

    def update(content: str) -> str:
        barrier.wait(timeout=2)
        return service.update(
            workspace=str(workspace), memory_id=entry.id, content=content
        ).content

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(update, ("first update", "second update")))

    assert set(responses) == {"first update", "second update"}
    assert service.list(str(workspace))[0].content in set(responses)


def test_concurrent_update_delete_has_a_linearizable_result(tmp_path):
    service, _database, root = _service(tmp_path)
    workspace = root / "project"
    workspace.mkdir()
    entry = service.create(workspace=str(workspace), kind="note", content="initial")
    barrier = threading.Barrier(2)

    def update() -> tuple[str, str]:
        barrier.wait(timeout=2)
        try:
            response = service.update(
                workspace=str(workspace),
                memory_id=entry.id,
                content="updated before delete",
            )
            return "updated", response.content
        except MemoryServiceError as exc:
            return "update_error", exc.code

    def delete() -> tuple[str, str]:
        barrier.wait(timeout=2)
        service.delete(workspace=str(workspace), memory_id=entry.id)
        return "deleted", "ok"

    with ThreadPoolExecutor(max_workers=2) as executor:
        update_future = executor.submit(update)
        delete_future = executor.submit(delete)
        results = {update_future.result(), delete_future.result()}

    assert ("deleted", "ok") in results
    assert results.intersection(
        {
            ("updated", "updated before delete"),
            ("update_error", "memory_not_found"),
        }
    )
    assert service.list(str(workspace)) == []


def test_corrupted_row_decode_degrades_to_store_unavailable(tmp_path):
    service, database, root = _service(tmp_path)
    workspace = root / "project"
    workspace.mkdir()
    entry = service.create(
        workspace=str(workspace), kind="note", content="CORRUPT_ROW_SECRET"
    )
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE memory_entries SET updated_at = ? WHERE id = ?",
            ("not-a-datetime-CORRUPT_ROW_SECRET", entry.id),
        )

    with pytest.raises(MemoryServiceError) as listed:
        service.list(str(workspace))
    assert listed.value.code == "memory_store_unavailable"
    assert "CORRUPT_ROW_SECRET" not in listed.value.message

    with pytest.raises(MemoryServiceError) as snapshot:
        service.snapshot(workspace=workspace, task="current task")
    assert snapshot.value.code == "memory_store_unavailable"
