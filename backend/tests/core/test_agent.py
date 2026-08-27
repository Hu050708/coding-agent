from __future__ import annotations

from copy import deepcopy
import json

import pytest

from clearloop.core import (
    AdapterRequestError,
    Agent,
    AgentConfig,
    AgentStatus,
    AssistantMessage,
    ModelCompletion,
    TerminationReason,
    TokenUsage,
    ToolCall,
    ToolExecutor,
    ToolRegistry,
)
from clearloop.core.agent import AgentStatus as AgentModuleStatus
from clearloop.core.contracts import AgentStatus as ContractStatus


class FakeAdapter:
    model = "deepseek-v4-flash"

    def __init__(self, *items):
        self.items = list(items)
        self.calls: list[dict] = []

    def complete(self, messages, tools, *, timeout_seconds=None):
        self.calls.append(
            {
                "messages": deepcopy(list(messages)),
                "tools": deepcopy(list(tools)),
                "timeout_seconds": timeout_seconds,
            }
        )
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeRegistry:
    schemas = [
        {
            "type": "function",
            "function": {"name": "read_file", "parameters": {"type": "object"}},
        }
    ]

    def __init__(self, result=None):
        self.result = result or {"ok": True, "data": {"text": "hello"}, "meta": {}}
        self.calls: list[tuple[str, dict]] = []
        self.timeouts: list[float | None] = []

    def execute(self, name, arguments, *, timeout_seconds=None):
        self.calls.append((name, deepcopy(dict(arguments))))
        self.timeouts.append(timeout_seconds)
        return json.dumps(self.result, separators=(",", ":"))


class RecordingTrace:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event, **fields):
        self.events.append((event, deepcopy(fields)))


class TickingClock:
    def __init__(self, *, start=0.0, step=1.0):
        self.value = start - step
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


class ScriptedClock:
    def __init__(self, values):
        self.values = iter(values)
        self.last = 0.0

    def __call__(self):
        self.last = next(self.values, self.last)
        return self.last


def final_completion(content="done", *, reasoning="final reasoning", usage=5):
    return ModelCompletion(
        finish_reason="stop",
        assistant=AssistantMessage(content=content, reasoning_content=reasoning),
        usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=usage),
        model="DeepSeek-V4-Flash-0731",
        system_fingerprint="fp",
    )


def tool_completion(arguments='{"path":"a.py"}', *, call_id="call-1"):
    return ModelCompletion(
        finish_reason="tool_calls",
        assistant=AssistantMessage(
            content=None,
            reasoning_content="tool reasoning",
            tool_calls=(
                ToolCall(
                    id=call_id,
                    name="read_file",
                    arguments=arguments,
                ),
            ),
        ),
        usage=TokenUsage(prompt_tokens=4, completion_tokens=3, total_tokens=7),
        model="DeepSeek-V4-Flash-0731",
    )


def make_agent(adapter, registry=None, **kwargs):
    return Agent(
        adapter,
        registry or FakeRegistry(),
        sleeper=lambda _delay: None,
        random_source=lambda: 0.0,
        run_id_factory=lambda: "run-test",
        **kwargs,
    )


def test_core_public_imports_remain_compatible_after_module_split():
    assert AgentStatus is AgentModuleStatus is ContractStatus
    assert ToolRegistry is ToolExecutor


def test_agent_preserves_reasoning_and_tool_calls_across_rounds():
    adapter = FakeAdapter(tool_completion(), final_completion())
    registry = FakeRegistry()
    trace = RecordingTrace()

    result = make_agent(adapter, registry, trace=trace).run("inspect and fix")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert result.reason is TerminationReason.MODEL_FINAL
    assert result.final_content == "done"
    assert result.model_calls == 2
    assert result.tool_calls == 1
    assert registry.calls == [("read_file", {"path": "a.py"})]
    assert [message["role"] for message in result.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    second_request = adapter.calls[1]["messages"]
    assert second_request[2]["reasoning_content"] == "tool reasoning"
    assert second_request[2]["tool_calls"][0]["function"]["arguments"] == '{"path":"a.py"}'
    assert second_request[3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"ok":true,"data":{"text":"hello"},"meta":{}}',
    }
    assert [event for event, _fields in trace.events] == [
        "run_started",
        "model_completed",
        "tool_started",
        "tool_completed",
        "model_completed",
        "run_finished",
    ]
    model_events = [fields for event, fields in trace.events if event == "model_completed"]
    assert model_events[0]["response_model"] == "DeepSeek-V4-Flash-0731"
    serialized_trace = repr(trace.events)
    assert "inspect and fix" not in serialized_trace
    assert "tool reasoning" not in serialized_trace
    assert '"path"' not in serialized_trace


def test_insufficient_system_resource_is_discarded_and_same_request_is_retried():
    unavailable = ModelCompletion(
        finish_reason="insufficient_system_resource",
        assistant=AssistantMessage(
            content="must be discarded",
            reasoning_content="must also be discarded",
        ),
        usage=TokenUsage(total_tokens=2),
    )
    adapter = FakeAdapter(unavailable, final_completion())

    result = make_agent(adapter).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert result.model_calls == 2
    assert adapter.calls[0]["messages"] == adapter.calls[1]["messages"]
    assert [message["role"] for message in result.messages] == ["system", "user", "assistant"]
    assert "must be discarded" not in repr(result.messages)


@pytest.mark.parametrize(
    "finish_reason,expected",
    [
        ("length", TerminationReason.TRUNCATED_RESPONSE),
        ("content_filter", TerminationReason.CONTENT_FILTERED),
        ("unexpected", TerminationReason.PROTOCOL_ERROR),
    ],
)
def test_non_success_finish_reasons_never_enter_history(finish_reason, expected):
    completion = ModelCompletion(
        finish_reason=finish_reason,
        assistant=AssistantMessage(content="must not enter history", reasoning_content="private"),
    )

    result = make_agent(FakeAdapter(completion)).run("task")

    assert result.status is AgentStatus.FAILED
    assert result.reason is expected
    assert [message["role"] for message in result.messages] == ["system", "user"]
    assert "must not enter history" not in repr(result.messages)


def test_protocol_conflicts_never_enter_history():
    duplicate_calls = ModelCompletion(
        finish_reason="tool_calls",
        assistant=AssistantMessage(
            tool_calls=(
                ToolCall(id="same", name="read_file", arguments="{}"),
                ToolCall(id="same", name="read_file", arguments="{}"),
            )
        ),
    )
    result = make_agent(FakeAdapter(duplicate_calls)).run("task")
    assert result.reason is TerminationReason.PROTOCOL_ERROR
    assert len(result.messages) == 2

    empty_stop = ModelCompletion(finish_reason="stop", assistant=AssistantMessage(content=""))
    result = make_agent(FakeAdapter(empty_stop)).run("task")
    assert result.reason is TerminationReason.PROTOCOL_ERROR
    assert len(result.messages) == 2


def test_tool_call_ids_must_be_unique_for_the_entire_run():
    adapter = FakeAdapter(
        tool_completion(call_id="reused"),
        tool_completion(call_id="reused"),
    )
    registry = FakeRegistry()

    result = make_agent(adapter, registry).run("task")

    assert result.status is AgentStatus.FAILED
    assert result.reason is TerminationReason.PROTOCOL_ERROR
    assert registry.calls == [("read_file", {"path": "a.py"})]
    assert [message["role"] for message in result.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":1e999}',
        '["not", "an", "object"]',
        '{"duplicate":1,"duplicate":2}',
        "not-json",
    ],
)
def test_tool_arguments_are_strict_json_objects(arguments):
    adapter = FakeAdapter(tool_completion(arguments), final_completion())
    registry = FakeRegistry()

    result = make_agent(adapter, registry).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert registry.calls == []
    tool_result = json.loads(result.messages[3]["content"])
    assert tool_result["ok"] is False
    assert tool_result["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    "bad_result",
    [
        "not-json",
        "[]",
        '{"ok":"yes"}',
        '{"ok":NaN}',
    ],
)
def test_invalid_registry_results_are_replaced_before_history(bad_result):
    class InvalidResultRegistry(FakeRegistry):
        def execute(self, name, arguments, *, timeout_seconds=None):
            self.calls.append((name, deepcopy(dict(arguments))))
            self.timeouts.append(timeout_seconds)
            return bad_result

    adapter = FakeAdapter(tool_completion(), final_completion())
    registry = InvalidResultRegistry()

    result = make_agent(adapter, registry).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    payload = json.loads(result.messages[3]["content"])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_tool_result"
    assert bad_result != result.messages[3]["content"]


def test_tool_completed_trace_uses_registry_command_metadata_shape():
    registry = FakeRegistry(
        {
            "ok": True,
            "data": {"exit_code": 7, "stdout": "sensitive output"},
            "meta": {"stdout_truncated": False, "stderr_truncated": True},
        }
    )
    trace = RecordingTrace()

    result = make_agent(
        FakeAdapter(tool_completion(), final_completion()),
        registry,
        trace=trace,
        clock=lambda: 0.0,
    ).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    completed = [fields for event, fields in trace.events if event == "tool_completed"]
    assert completed == [
        {
            "run_id": "run-test",
            "sequence": 1,
            "tool": "read_file",
            "ok": True,
            "error_code": None,
            "exit_code": 7,
            "duration_ms": 0,
            "truncated": True,
        }
    ]
    assert "sensitive output" not in repr(trace.events)


def test_unknown_model_tool_name_is_redacted_before_trace_emission():
    secret_tool_name = "TRACE_CONTENT_MARKER_9f31"
    completion = ModelCompletion(
        finish_reason="tool_calls",
        assistant=AssistantMessage(
            tool_calls=(
                ToolCall(id="unknown-1", name=secret_tool_name, arguments="{}"),
            )
        ),
    )
    registry = FakeRegistry()
    trace = RecordingTrace()

    result = make_agent(
        FakeAdapter(completion, final_completion()),
        registry,
        trace=trace,
    ).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert registry.calls == [(secret_tool_name, {})]
    tool_events = [fields for event, fields in trace.events if event.startswith("tool_")]
    assert [fields["tool"] for fields in tool_events] == [
        "unknown_tool",
        "unknown_tool",
    ]
    assert secret_tool_name not in repr(trace.events)


def test_same_round_tool_failure_does_not_cancel_later_tool_calls():
    class MixedRegistry(FakeRegistry):
        schemas = [
            {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
            for name in ("first", "second")
        ]

        def execute(self, name, arguments, *, timeout_seconds=None):
            self.calls.append((name, deepcopy(dict(arguments))))
            self.timeouts.append(timeout_seconds)
            if name == "first":
                return '{"ok":false,"error":{"code":"expected_failure"}}'
            return '{"ok":true,"data":{},"meta":{}}'

    completion = ModelCompletion(
        finish_reason="tool_calls",
        assistant=AssistantMessage(
            reasoning_content="multi-tool reasoning",
            tool_calls=(
                ToolCall(id="multi-a", name="first", arguments="{}"),
                ToolCall(id="multi-b", name="second", arguments="{}"),
            ),
        ),
    )
    adapter = FakeAdapter(completion, final_completion())
    registry = MixedRegistry()

    result = make_agent(adapter, registry).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert registry.calls == [("first", {}), ("second", {})]
    tool_messages = [message for message in result.messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["multi-a", "multi-b"]
    assert [json.loads(message["content"])["ok"] for message in tool_messages] == [
        False,
        True,
    ]
    assert [message["role"] for message in adapter.calls[1]["messages"][-3:]] == [
        "assistant",
        "tool",
        "tool",
    ]


def test_retryable_request_error_retries_without_changing_history():
    adapter = FakeAdapter(
        AdapterRequestError("temporary", retryable=True, status_code=429),
        final_completion(),
    )

    result = make_agent(adapter).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert result.model_calls == 2
    assert adapter.calls[0]["messages"] == adapter.calls[1]["messages"]


@pytest.mark.parametrize(
    "first_response",
    [
        AdapterRequestError("temporary", retryable=True, status_code=429),
        ModelCompletion(finish_reason="insufficient_system_resource"),
    ],
)
def test_model_call_limit_prevents_backoff_after_last_attempt(first_response):
    sleeps: list[float] = []
    result = Agent(
        FakeAdapter(first_response),
        FakeRegistry(),
        config=AgentConfig(
            max_model_calls=1,
            wall_time_seconds=1,
            retry_base_seconds=1,
            retry_jitter_seconds=0,
        ),
        clock=lambda: 0.0,
        sleeper=sleeps.append,
        random_source=lambda: 0.0,
        run_id_factory=lambda: "run-test",
    ).run("task")

    assert result.status is AgentStatus.BUDGET_EXHAUSTED
    assert result.reason is TerminationReason.MAX_MODEL_CALLS
    assert result.model_calls == 1
    assert result.duration_seconds == 0
    assert sleeps == []


def test_retryable_request_errors_stop_after_retry_budget():
    adapter = FakeAdapter(
        AdapterRequestError("temporary", retryable=True, status_code=429),
        AdapterRequestError("temporary", retryable=True, status_code=429),
        AdapterRequestError("temporary", retryable=True, status_code=429),
    )
    config = AgentConfig(
        max_transient_retries=2,
        retry_base_seconds=0,
        retry_jitter_seconds=0,
    )

    result = make_agent(adapter, config=config).run("task")

    assert result.status is AgentStatus.FAILED
    assert result.reason is TerminationReason.API_FATAL_ERROR
    assert result.model_calls == 3


def test_model_call_budget_stops_after_a_complete_tool_exchange():
    adapter = FakeAdapter(tool_completion())
    config = AgentConfig(max_model_calls=1, retry_base_seconds=0, retry_jitter_seconds=0)

    result = make_agent(adapter, config=config).run("task")

    assert result.status is AgentStatus.BUDGET_EXHAUSTED
    assert result.reason is TerminationReason.MAX_MODEL_CALLS
    assert [message["role"] for message in result.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]


def test_tool_call_budget_rejects_an_oversized_batch_before_execution():
    completion = ModelCompletion(
        finish_reason="tool_calls",
        assistant=AssistantMessage(
            tool_calls=(
                ToolCall(id="budget-a", name="read_file", arguments="{}"),
                ToolCall(id="budget-b", name="read_file", arguments="{}"),
            )
        ),
    )
    registry = FakeRegistry()

    result = make_agent(
        FakeAdapter(completion),
        registry,
        config=AgentConfig(max_tool_calls=1),
    ).run("task")

    assert result.status is AgentStatus.BUDGET_EXHAUSTED
    assert result.reason is TerminationReason.MAX_TOOL_CALLS
    assert registry.calls == []
    assert [message["role"] for message in result.messages] == ["system", "user"]


def test_token_budget_rejects_an_over_budget_response_before_history_commit():
    result = make_agent(
        FakeAdapter(final_completion(usage=11)),
        config=AgentConfig(max_total_tokens=10),
    ).run("task")

    assert result.status is AgentStatus.BUDGET_EXHAUSTED
    assert result.reason is TerminationReason.TOKEN_BUDGET_EXCEEDED
    assert result.final_content is None
    assert [message["role"] for message in result.messages] == ["system", "user"]


@pytest.mark.parametrize(
    "field_name",
    [
        "wall_time_seconds",
        "api_timeout_seconds",
        "retry_base_seconds",
        "retry_jitter_seconds",
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_agent_config_rejects_non_finite_time_values(field_name, value):
    with pytest.raises(ValueError, match="finite"):
        AgentConfig(**{field_name: value})


def test_agent_passes_remaining_wall_time_to_every_tool_execution():
    registry = FakeRegistry()
    config = AgentConfig(wall_time_seconds=100)

    result = make_agent(
        FakeAdapter(tool_completion(), final_completion()),
        registry,
        config=config,
        clock=TickingClock(),
    ).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert len(registry.timeouts) == 1
    assert registry.timeouts[0] is not None
    assert 0 < registry.timeouts[0] < config.wall_time_seconds


def test_agent_does_not_start_tool_when_deadline_expires_after_argument_parsing():
    registry = FakeRegistry()
    clock = ScriptedClock([0.0] * 8 + [101.0])

    result = make_agent(
        FakeAdapter(tool_completion()),
        registry,
        config=AgentConfig(wall_time_seconds=100),
        clock=clock,
    ).run("task")

    assert result.status is AgentStatus.BUDGET_EXHAUSTED
    assert result.reason is TerminationReason.WALL_TIME_EXCEEDED
    assert registry.calls == []
    payload = json.loads(result.messages[-1]["content"])
    assert payload["error"]["code"] == "wall_time_exceeded"


def test_trace_failures_do_not_change_run_result():
    class BrokenTrace:
        def emit(self, event, **fields):
            raise RuntimeError("disk full")

    result = make_agent(FakeAdapter(final_completion()), trace=BrokenTrace()).run("task")

    assert result.status is AgentStatus.MODEL_FINISHED
    assert result.final_content == "done"
