"""验证 Web 服务组合、健康状态和生命周期收尾。"""

from __future__ import annotations

import asyncio
import threading

import pytest

from coding_agent.settings import AppSettings
from coding_agent.agents.runtime.event_buffer import EventBuffer
from coding_agent.agents.runtime.run_manager import BufferTrace
from coding_agent.agents.security import WorkspacePolicy, WorkspacePolicyError


def test_settings_load_env_file_without_exposing_secret(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f'DEEPSEEK_API_KEY="private-test-key"\nCODING_AGENT_ALLOWED_ROOT={tmp_path}\n',
        encoding="utf-8",
    )

    settings = AppSettings(_env_file=env_file)

    assert settings.api_key == "private-test-key"
    assert settings.api_key_configured is True
    assert "private-test-key" not in repr(settings)


def test_settings_accepts_direct_overrides(tmp_path):
    data_dir = tmp_path / "data"
    settings = AppSettings(
        api_key="x",
        allowed_root=tmp_path,
        data_dir=data_dir,
        database_url=(
            "postgresql+psycopg://coding_agent:local-secret@127.0.0.1:5434/coding_agent"
        ),
    )
    assert settings.database_configured is True
    assert settings.allowed_root == tmp_path
    assert settings.data_dir == data_dir
    assert "local-secret" not in repr(settings)


def test_workspace_policy_accepts_only_contained_existing_directories(tmp_path):
    allowed = tmp_path / "allowed"
    inside = allowed / "project"
    outside = tmp_path / "outside"
    inside.mkdir(parents=True)
    outside.mkdir()
    policy = WorkspacePolicy(allowed)

    assert policy.validate(str(inside)) == inside.resolve()
    with pytest.raises(WorkspacePolicyError) as exc_info:
        policy.validate(str(outside))
    assert exc_info.value.code == "workspace_not_allowed"
    with pytest.raises(WorkspacePolicyError) as exc_info:
        policy.validate("relative/path")
    assert exc_info.value.code == "workspace_not_absolute"


def test_event_buffer_replays_and_wakes_async_subscriber_from_thread():
    buffer = EventBuffer(max_events=2)
    first = buffer.publish("one", {"value": 1})
    buffer.publish("two", {"value": 2})
    third = buffer.publish("three", {"value": 3})

    events, gap = buffer.read_after(0)
    assert gap is True
    assert [event.seq for event in events] == [first.seq + 1, third.seq]

    async def scenario() -> None:
        subscription = buffer.subscribe()
        try:
            subscription.clear()
            thread = threading.Thread(target=lambda: buffer.publish("four", {"value": 4}))
            thread.start()
            assert await subscription.wait(1.0) is True
            thread.join(timeout=1)
        finally:
            subscription.close()

    asyncio.run(scenario())


def test_event_buffer_rejects_non_json_payload():
    buffer = EventBuffer()
    with pytest.raises((TypeError, ValueError)):
        buffer.publish("bad", {"value": float("nan")})


def test_event_buffer_serializes_persistence_callback_with_live_sequence():
    persisted = []
    buffer = EventBuffer(on_publish=persisted.append)

    first = buffer.publish("run.accepted", {"status": "starting"})
    second = buffer.publish("run.started", {"status": "running"})

    assert persisted == [first, second]
    assert [item.seq for item in persisted] == [1, 2]


def test_buffer_trace_normalizes_tool_name_for_the_web_contract():
    buffer = EventBuffer()
    BufferTrace(buffer).emit("tool_started", run_id="run", sequence=1, tool="read_file")

    events, gap = buffer.read_after(0)

    assert gap is False
    assert events[0].event == "tool.started"
    assert events[0].data["tool_name"] == "read_file"
    assert "tool" not in events[0].data
