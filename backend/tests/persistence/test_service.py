"""验证跨仓储事务、锁顺序和幂等运行语义。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from coding_agent.repository import (
    MemoryRepository,
    PersistenceConflictError,
    PersistenceNotFoundError,
)
from coding_agent.database import interrupt_stale_runs
from coding_agent.repository import RunStatus


def _conversation(service):
    workspace = service.create_workspace(
        canonical_path="E:/code/example",
        path_key="e:/code/example",
        display_name="example",
    )
    conversation = service.create_conversation(
        workspace_id=workspace.id,
        title="First task",
        default_permission_mode="agent",
        use_memory=True,
    )
    return workspace, conversation


def test_run_creation_is_atomic_idempotent_and_workspace_exclusive(persistence) -> None:
    service, _database = persistence
    workspace, conversation = _conversation(service)
    run_id = uuid4()
    first = service.create_run_with_user_message(
        conversation_id=conversation.id,
        content="Implement the feature",
        permission_mode="agent",
        use_memory=True,
        client_request_id="browser-request-1",
        run_id=run_id,
    )
    retry = service.create_run_with_user_message(
        conversation_id=conversation.id,
        content="This retry must not add another message",
        permission_mode="agent",
        use_memory=True,
        client_request_id="browser-request-1",
        run_id=run_id,
    )

    assert first.created is True
    assert first.run.workspace_id == workspace.id
    assert first.run.conversation_id == conversation.id
    assert first.user_message.conversation_id == conversation.id
    assert first.user_message.run_id == first.run.id
    assert retry.created is False
    assert retry.run.id == first.run.id
    assert retry.prior_messages == first.prior_messages == ()
    assert retry.memory_snapshot == first.memory_snapshot
    assert service.list_messages(conversation.id) == [first.user_message]
    assert service.active_run_for_workspace(workspace.id).id == first.run.id

    second_conversation = service.create_conversation(
        workspace_id=workspace.id, title="Second task"
    )
    with pytest.raises(PersistenceConflictError, match="active run"):
        service.create_run_with_user_message(
            conversation_id=second_conversation.id,
            content="Cannot overlap",
            permission_mode="ask",
            use_memory=False,
            client_request_id="browser-request-2",
        )


def test_visible_messages_and_explicit_event_sequences_round_trip(persistence) -> None:
    service, _database = persistence
    _workspace, conversation = _conversation(service)
    creation = service.create_run_with_user_message(
        conversation_id=conversation.id,
        content="Say hello",
        permission_mode="ask",
        use_memory=False,
        client_request_id="one",
    )
    timestamp = datetime.now(timezone.utc)
    event = service.append_safe_event(
        creation.run.id,
        seq=7,
        event="tool.completed",
        timestamp=timestamp,
        data={
            "sequence": 1,
            "tool_name": "read_file",
            "ok": True,
            "output": "must not be persisted",
        },
    )
    assert event.seq == 7
    assert event.data == {"sequence": 1, "tool_name": "read_file", "ok": True}
    assert service.next_event_sequence(creation.run.id) == 8
    assert service.list_events(creation.run.id, after_seq=6) == [event]

    finished, assistant = service.append_assistant_message_and_finish(
        creation.run.id,
        content="Hello",
        status="completed",
        reason="final_answer",
        model_calls=1,
        tool_calls=1,
        usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        duration_ms=25,
    )
    assert finished.status == "completed"
    assert assistant is not None
    assert [item.role for item in service.history(conversation.id)] == ["user", "assistant"]

    next_run = service.create_run_with_user_message(
        conversation_id=conversation.id,
        content="Continue",
        permission_mode="ask",
        use_memory=False,
        client_request_id="two",
    )
    assert [item.role for item in next_run.prior_messages] == ["user", "assistant"]


def test_memory_is_confirmed_crud_and_snapshot_is_immutable(persistence) -> None:
    service, _database = persistence
    workspace, conversation = _conversation(service)
    memory = service.create_memory(
        workspace_id=workspace.id,
        kind="preference",
        content="Use pytest for backend tests",
        pinned=True,
    )
    assert memory.confirmed_at is not None
    assert service.list_memories(workspace.id) == [memory]
    updated = service.update_memory(
        workspace.id, memory.id, kind="decision", enabled=True
    )
    assert updated.kind == "decision"

    creation = service.create_run_with_user_message(
        conversation_id=conversation.id,
        content="Add tests",
        permission_mode="agent",
        use_memory=True,
        client_request_id="memory-run",
    )
    snapshots = creation.memory_snapshot
    assert [item.content for item in snapshots] == ["Use pytest for backend tests"]
    with pytest.raises(PersistenceConflictError, match="immutable"):
        service.snapshot_memories(run_id=creation.run.id)

    for mutation in (
        lambda: service.create_memory(
            workspace_id=workspace.id, kind="note", content="Blocked while active"
        ),
        lambda: service.update_memory(
            workspace.id, memory.id, content="Blocked while active"
        ),
        lambda: service.delete_memory(workspace.id, memory.id),
        lambda: service.purge_memories(workspace.id),
        lambda: service.archive_workspace(workspace.id),
    ):
        with pytest.raises(PersistenceConflictError, match="active run"):
            mutation()

    service.append_assistant_message_and_finish(
        creation.run.id,
        content="Memory snapshot used",
        status="completed",
        reason="final_answer",
        model_calls=1,
        tool_calls=0,
        usage={},
        duration_ms=1,
    )
    service.delete_memory(workspace.id, memory.id)
    assert service.list_memories(workspace.id) == []
    assert service.list_run_memories(creation.run.id)[0].content == snapshots[0].content


def test_conversation_and_memory_mutations_are_workspace_scoped(persistence) -> None:
    service, _database = persistence
    first_workspace, conversation = _conversation(service)
    second_workspace = service.create_workspace(
        canonical_path="E:/code/other",
        path_key="e:/code/other",
        display_name="other",
    )
    memory = service.create_memory(
        workspace_id=first_workspace.id,
        kind="note",
        content="Belongs only to the first workspace",
    )

    with pytest.raises(PersistenceNotFoundError, match="conversation was not found"):
        service.rename_conversation(
            second_workspace.id, conversation.id, title="Cross-workspace rename"
        )
    with pytest.raises(PersistenceNotFoundError, match="memory entry was not found"):
        service.update_memory(
            second_workspace.id, memory.id, content="Cross-workspace overwrite"
        )
    with pytest.raises(PersistenceNotFoundError, match="memory entry was not found"):
        service.delete_memory(second_workspace.id, memory.id)

    updated = service.update_conversation(
        first_workspace.id,
        conversation.id,
        title="Updated task",
        default_permission_mode="workspace_full",
        use_memory=False,
    )
    assert (updated.title, updated.default_permission_mode, updated.use_memory) == (
        "Updated task",
        "workspace_full",
        False,
    )


def test_startup_interrupts_active_runs_and_pending_approvals(persistence) -> None:
    service, database = persistence
    _workspace, conversation = _conversation(service)
    creation = service.create_run_with_user_message(
        conversation_id=conversation.id,
        content="Long task",
        permission_mode="agent",
        use_memory=False,
        client_request_id="restart",
    )
    service.create_approval(
        approval_id=uuid4(),
        run_id=creation.run.id,
        tool_name="run_command",
        action_summary="Run project tests",
        reason="Needs confirmation",
        expires_at=datetime.now(timezone.utc).replace(year=2027),
    )
    service.append_safe_event(
        creation.run.id,
        seq=3,
        event="run.accepted",
        timestamp=datetime.now(timezone.utc),
        data={"run_id": str(creation.run.id), "status": "starting"},
    )

    assert interrupt_stale_runs(database.session_factory) == 1
    run = service.get_run(creation.run.id)
    assert run.status == RunStatus.INTERRUPTED.value
    assert run.reason == "server_restart"
    events = service.list_events(creation.run.id)
    assert [(item.seq, item.event) for item in events] == [
        (3, "run.accepted"),
        (4, "run.interrupted"),
    ]
    assert events[-1].data["reason"] == "server_restart"
    assert interrupt_stale_runs(database.session_factory) == 0


def test_cancel_request_is_idempotent_until_the_run_is_terminal(persistence) -> None:
    service, _database = persistence
    _workspace, conversation = _conversation(service)
    creation = service.create_run_with_user_message(
        conversation_id=conversation.id,
        content="Cancelable task",
        permission_mode="agent",
        use_memory=False,
        client_request_id="cancel",
    )

    first = service.request_cancel(creation.run.id)
    retry = service.request_cancel(creation.run.id)
    assert first.status == retry.status == "cancelling"
    assert first.cancel_requested_at == retry.cancel_requested_at

    service.append_assistant_message_and_finish(
        creation.run.id,
        content=None,
        status="cancelled",
        reason="user_cancelled",
        model_calls=0,
        tool_calls=0,
        usage={},
        duration_ms=1,
    )
    with pytest.raises(PersistenceConflictError, match="terminal"):
        service.request_cancel(creation.run.id)


@pytest.mark.parametrize(
    ("item_size", "expected_count", "expected_chars"),
    [(1_000, 32, 32_000), (1_001, 31, 31_031)],
)
def test_run_memory_snapshot_matches_context_builder_budgets(
    persistence, item_size, expected_count, expected_chars
) -> None:
    service, database = persistence
    workspace, conversation = _conversation(service)
    with database.session_factory.begin() as session:
        memories = MemoryRepository(session)
        for index in range(40):
            prefix = f"{index:04d}"
            memories.create(
                workspace_id=workspace.id,
                kind="note",
                content=prefix + ("x" * (item_size - len(prefix))),
            )

    creation = service.create_run_with_user_message(
        conversation_id=conversation.id,
        content="Use the bounded memory snapshot",
        permission_mode="ask",
        use_memory=True,
        client_request_id=f"budget-{item_size}",
    )
    assert len(creation.memory_snapshot) == expected_count
    assert sum(len(item.content) for item in creation.memory_snapshot) == expected_chars


def test_memory_content_limit_matches_public_api_contract(persistence) -> None:
    service, _database = persistence
    workspace, _conversation_value = _conversation(service)
    with pytest.raises(ValueError, match="2000"):
        service.create_memory(
            workspace_id=workspace.id,
            kind="note",
            content="x" * 2_001,
        )
