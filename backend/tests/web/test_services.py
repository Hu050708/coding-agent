from __future__ import annotations

import asyncio
import threading

import pytest

from coding_agent.config import AppSettings, SettingsError
from coding_agent.runs.event_buffer import EventBuffer
from coding_agent.runs.run_manager import BufferTrace
from coding_agent.security import WorkspacePolicy, WorkspacePolicyError


def test_settings_load_env_file_without_exposing_secret(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f'DEEPSEEK_API_KEY="private-test-key"\nCODING_AGENT_ALLOWED_ROOT={tmp_path}\n',
        encoding="utf-8",
    )

    settings = AppSettings.from_environment({}, env_file=env_file)

    assert settings.api_key == "private-test-key"
    assert settings.api_key_configured is True
    assert "private-test-key" not in repr(settings)


def test_settings_reject_non_loopback_host(tmp_path):
    with pytest.raises(SettingsError, match="127.0.0.1"):
        AppSettings(api_key="x", allowed_root=tmp_path, host="0.0.0.0")


def test_settings_accepts_explicit_memory_data_directory(tmp_path):
    data_dir = tmp_path.parent / f"{tmp_path.name}-private-memory-data"
    settings = AppSettings.from_environment(
        {
            "DEEPSEEK_API_KEY": "test-key",
            "CODING_AGENT_ALLOWED_ROOT": str(tmp_path),
            "CODING_AGENT_DATA_DIR": str(data_dir),
        },
        env_file=None,
    )

    assert settings.data_dir == data_dir.resolve()


@pytest.mark.parametrize("data_dir", [".", "private-memory-data"])
def test_settings_rejects_memory_data_inside_allowed_root(tmp_path, data_dir):
    target = tmp_path if data_dir == "." else tmp_path / data_dir
    with pytest.raises(SettingsError, match="outside CODING_AGENT_ALLOWED_ROOT"):
        AppSettings(api_key="x", allowed_root=tmp_path, data_dir=target)


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


def test_buffer_trace_normalizes_tool_name_for_the_web_contract():
    buffer = EventBuffer()
    BufferTrace(buffer).emit("tool_started", run_id="run", sequence=1, tool="read_file")

    events, gap = buffer.read_after(0)

    assert gap is False
    assert events[0].event == "tool.started"
    assert events[0].data["tool_name"] == "read_file"
    assert "tool" not in events[0].data
