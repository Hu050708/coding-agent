"""验证历史消息和记忆上下文的校验与渲染。"""

from __future__ import annotations

import json

import pytest

from coding_agent.agents import (
    AgentConfig,
    AgentContext,
    AgentContextBuilder,
    MemoryReference,
    VisibleMessage,
)


def test_context_accepts_only_visible_user_and_assistant_records() -> None:
    builder = AgentContextBuilder()
    context = builder.build(
        prior_messages=(
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
        )
    )
    assert context.prior_messages == (
        VisibleMessage("user", "first"),
        VisibleMessage("assistant", "answer"),
    )

    with pytest.raises(ValueError, match="role"):
        builder.build(prior_messages=({"role": "tool", "content": "raw output"},))
    with pytest.raises(ValueError, match="reasoning"):
        builder.build(
            prior_messages=(
                {"role": "assistant", "content": "visible", "reasoning_content": "hidden"},
            )
        )


def test_context_keeps_newest_messages_within_budgets() -> None:
    context = AgentContextBuilder().build(
        config=AgentConfig(
            max_prior_messages=2,
            max_prior_chars=5,
            max_message_chars=4,
        ),
        prior_messages=(
            VisibleMessage("user", "old"),
            VisibleMessage("assistant", "bb"),
            VisibleMessage("user", "ccc"),
        ),
    )
    assert [message.content for message in context.prior_messages] == ["bb", "ccc"]
    assert context.dropped_prior_messages == 1


def test_oversized_persisted_message_is_a_recoverable_truncation_boundary() -> None:
    context = AgentContextBuilder().build(
        config=AgentConfig(
            max_prior_messages=10,
            max_prior_chars=100,
            max_message_chars=8,
        ),
        prior_messages=(
            VisibleMessage("user", "older"),
            VisibleMessage("assistant", "x" * 20),
            VisibleMessage("user", "latest"),
        ),
    )

    assert context.prior_messages == (VisibleMessage("user", "latest"),)
    assert context.dropped_prior_messages == 2

    latest_too_large = AgentContextBuilder().build(
        config=AgentConfig(max_message_chars=4),
        prior_messages=(VisibleMessage("user", "persisted valid long request"),),
    )
    assert latest_too_large.prior_messages == ()
    assert latest_too_large.dropped_prior_messages == 1


def test_memory_is_immutable_user_data_with_current_task_last() -> None:
    context = AgentContextBuilder().build(
        memory_entries=(MemoryReference("m1", "decision", "Use pytest"),)
    )
    payload = json.loads(context.render_current_task("Fix one test"))
    assert payload["workspace_memory"] == [
        {"id": "m1", "kind": "decision", "content": "Use pytest"}
    ]
    assert list(payload)[-1] == "current_task"
    assert payload["current_task"] == "Fix one test"


def test_memory_limits_come_from_agent_config() -> None:
    context = AgentContextBuilder().build(
        config=AgentConfig(
            max_memory_entries=2,
            max_memory_chars=5,
            max_memory_item_chars=4,
        ),
        memory_entries=(
            MemoryReference("m1", "decision", "abc"),
            MemoryReference("m2", "fact", "de"),
            MemoryReference("m3", "fact", "f"),
        ),
    )

    assert [entry.id for entry in context.memory_entries] == ["m1", "m2"]


def test_prior_history_is_one_compact_json_transcript() -> None:
    context = AgentContextBuilder().build(
        prior_messages=(
            VisibleMessage("user", "检查中文.py"),
            VisibleMessage("assistant", "已检查"),
        )
    )

    rendered = context.render_prior_transcript()
    assert rendered is not None
    assert "检查中文.py" in rendered
    payload = json.loads(rendered)
    assert payload["type"] == "coding_agent_visible_history"
    assert payload["messages"] == [
        {"role": "user", "content": "检查中文.py"},
        {"role": "assistant", "content": "已检查"},
    ]


def test_empty_prior_history_does_not_render_a_transcript() -> None:
    assert AgentContext().render_prior_transcript() is None


def test_agent_context_requires_immutable_tuples() -> None:
    with pytest.raises(TypeError, match="immutable tuple"):
        AgentContext(prior_messages=[VisibleMessage("user", "x")])  # type: ignore[arg-type]
