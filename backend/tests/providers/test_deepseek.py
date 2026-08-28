"""验证 DeepSeek 响应规范化、错误分类和请求参数。"""

from __future__ import annotations

from copy import deepcopy
import json

import httpx
import pytest
from openai import OpenAI
from openai.types.chat import ChatCompletion

from coding_agent.agents import AdapterProtocolError, AdapterRequestError
from coding_agent.agents.providers.deepseek import DeepSeekAdapter, normalize_completion


class FakeCompletions:
    def __init__(self, *items):
        self.items = list(items)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClient:
    def __init__(self, *items):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions(*items)


class ClosableFakeClient(FakeClient):
    def __init__(self, *items):
        super().__init__(*items)
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class FailingCloseFakeClient(FakeClient):
    def __init__(self, *items):
        super().__init__(*items)
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        raise RuntimeError("DeepSeek_Api_Key=secret; private response body")


def response(
    *,
    finish_reason="stop",
    content="done",
    reasoning_content="private reasoning",
    tool_calls=None,
    usage=None,
):
    return {
        "id": "completion-1",
        "model": "DeepSeek-V4-Flash-0731",
        "system_fingerprint": "fp-test",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning_content,
                    "tool_calls": tool_calls,
                },
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
            "prompt_cache_hit_tokens": 3,
        },
    }


def test_adapter_uses_only_fixed_chat_completions_parameters():
    raw = response(
        finish_reason="tool_calls",
        content=None,
        tool_calls=[
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
            }
        ],
    )
    client = FakeClient(raw)
    adapter = DeepSeekAdapter(client, max_tokens=8192, timeout_seconds=30)
    messages = [{"role": "user", "content": "inspect"}]
    tools = [
        {
            "type": "function",
            "function": {"name": "read_file", "parameters": {"type": "object"}},
        }
    ]

    completion = adapter.complete(messages, tools, timeout_seconds=12)

    request = client.chat.completions.calls[0]
    assert request == {
        "model": "deepseek-v4-flash",
        "messages": messages,
        "tools": tools,
        "stream": False,
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}},
        "max_tokens": 8192,
        "timeout": 12.0,
    }
    assert "temperature" not in request
    assert "top_p" not in request
    assert completion.finish_reason == "tool_calls"
    assert completion.assistant.reasoning_content == "private reasoning"
    assert completion.assistant.as_history_dict() == {
        "role": "assistant",
        "content": "",
        "reasoning_content": "private reasoning",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
            }
        ],
    }
    assert completion.usage.total_tokens == 18
    assert completion.usage.prompt_cache_hit_tokens == 3
    assert completion.model == "DeepSeek-V4-Flash-0731"
    assert completion.system_fingerprint == "fp-test"


def test_adapter_preserves_deepseek_extra_fields_on_real_sdk_objects():
    raw = response(
        finish_reason="tool_calls",
        content=None,
        reasoning_content="sdk-preserved reasoning",
        tool_calls=[
            {
                "id": "call-sdk",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
    )
    raw.update({"object": "chat.completion", "created": 0})
    sdk_response = ChatCompletion.model_validate(raw)
    adapter = DeepSeekAdapter(FakeClient(sdk_response))

    completion = adapter.complete([{"role": "user", "content": "x"}], [])

    assert completion.assistant.reasoning_content == "sdk-preserved reasoning"
    assert completion.assistant.tool_calls[0].id == "call-sdk"


def test_openai_sdk_wire_json_preserves_deepseek_reasoning_and_tools():
    captured: dict = {}
    timeout_extension: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        timeout_extension.update(request.extensions["timeout"])
        raw = response(reasoning_content="response reasoning")
        raw.update({"object": "chat.completion", "created": 0})
        return httpx.Response(200, json=raw)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAI(
        api_key="offline-dummy",
        base_url="https://example.invalid",
        max_retries=0,
        http_client=http_client,
    )
    adapter = DeepSeekAdapter(client, timeout_seconds=30)
    messages = [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "history reasoning",
            "tool_calls": [
                {
                    "id": "call-wire",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-wire", "content": '{"ok":true}'},
    ]
    tools = [
        {
            "type": "function",
            "function": {"name": "read_file", "parameters": {"type": "object"}},
        }
    ]

    try:
        completion = adapter.complete(messages, tools, timeout_seconds=12)
    finally:
        client.close()

    assert captured["messages"] == messages
    assert captured["tools"] == tools
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "high"
    assert "tool_choice" not in captured
    assert captured["stream"] is False
    assert captured["max_tokens"] == 8192
    assert "extra_body" not in captured
    assert timeout_extension == {
        "connect": 12.0,
        "read": 12.0,
        "write": 12.0,
        "pool": 12.0,
    }
    assert completion.assistant.reasoning_content == "response reasoning"


@pytest.mark.parametrize(
    "finish_reason", ["length", "content_filter", "insufficient_system_resource"]
)
def test_non_historical_finish_reasons_do_not_parse_partial_message(finish_reason):
    raw = response(finish_reason=finish_reason)
    raw["choices"][0]["message"] = {"role": "broken", "tool_calls": "partial"}

    completion = normalize_completion(raw)

    assert completion.finish_reason == finish_reason
    assert completion.assistant.content is None
    assert completion.assistant.reasoning_content is None
    assert completion.assistant.tool_calls == ()


def test_malformed_success_response_is_a_protocol_error():
    with pytest.raises(AdapterProtocolError, match="exactly one choice"):
        normalize_completion({"choices": []})

    malformed_call = response(
        finish_reason="tool_calls",
        content=None,
        tool_calls=[
            {
                "id": "call-1",
                "type": "hosted_tool",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
    )
    with pytest.raises(AdapterProtocolError, match="only function"):
        normalize_completion(malformed_call)

class FakeHTTPFailure(RuntimeError):
    def __init__(self, status_code):
        super().__init__("response body must not be copied into adapter errors")
        self.status_code = status_code


@pytest.mark.parametrize("status_code,retryable", [(429, True), (500, True), (503, True), (400, False)])
def test_request_errors_are_sanitized_and_classified(status_code, retryable):
    client = FakeClient(FakeHTTPFailure(status_code))
    adapter = DeepSeekAdapter(client)

    with pytest.raises(AdapterRequestError) as caught:
        adapter.complete([{"role": "user", "content": "x"}], [])

    assert caught.value.status_code == status_code
    assert caught.value.retryable is retryable
    assert "response body" not in str(caught.value)


def test_constructor_requires_explicit_key_or_injected_client():
    with pytest.raises(ValueError, match="api_key is required"):
        DeepSeekAdapter()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_adapter_rejects_non_finite_constructor_timeout(value):
    with pytest.raises(ValueError, match="finite"):
        DeepSeekAdapter(FakeClient(), timeout_seconds=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_adapter_rejects_non_finite_per_request_timeout(value):
    adapter = DeepSeekAdapter(FakeClient())

    with pytest.raises(ValueError, match="finite"):
        adapter.complete([{"role": "user", "content": "x"}], [], timeout_seconds=value)


def test_adapter_close_calls_underlying_client_once():
    client = ClosableFakeClient()
    adapter = DeepSeekAdapter(client)

    assert adapter.close() is None
    assert adapter.close() is None

    assert client.close_calls == 1


def test_adapter_close_is_safe_when_client_has_no_close():
    adapter = DeepSeekAdapter(FakeClient())

    assert adapter.close() is None
    assert adapter.close() is None


def test_adapter_close_suppresses_and_does_not_expose_client_error(capsys):
    client = FailingCloseFakeClient()
    adapter = DeepSeekAdapter(client)

    assert adapter.close() is None
    assert adapter.close() is None

    assert client.close_calls == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.out
    assert "secret" not in captured.err
    assert "private response" not in captured.out
    assert "private response" not in captured.err
