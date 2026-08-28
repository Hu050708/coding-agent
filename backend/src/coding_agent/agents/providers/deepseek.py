"""基于官方 OpenAI Python 客户端实现 DeepSeek Chat Completions 适配器。

SDK 仅用于 HTTP 传输和响应数据对象。本模块不解析工具参数、不执行工具、不管理
历史，也不运行智能体循环；这些职责仍属于 :mod:`coding_agent.agents.agent`。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import math
from threading import Lock
from typing import Any

from openai import APIConnectionError, APITimeoutError, OpenAI

from coding_agent.agents.contracts import (
    AdapterProtocolError,
    AdapterRequestError,
    AssistantMessage,
    ModelCompletion,
    TokenUsage,
    ToolCall,
)


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TIMEOUT_SECONDS = 60.0

_MISSING = object()
_NON_HISTORICAL_FINISH_REASONS = {
    "length",
    "content_filter",
    "insufficient_system_resource",
}


def _is_finite_positive_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _field(value: Any, name: str, default: Any = _MISSING) -> Any:
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
    else:
        try:
            return getattr(value, name)
        except AttributeError:
            pass
    if default is _MISSING:
        raise AdapterProtocolError(f"model response is missing {name!r}")
    return default


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterProtocolError(f"{field_name} must be text or null")
    return value


def _optional_nonnegative_int(value: Any, field_name: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterProtocolError(f"usage.{field_name} must be a non-negative integer")
    return value


def _normalize_usage(raw_usage: Any) -> TokenUsage:
    if raw_usage is None:
        return TokenUsage()
    prompt_tokens = _optional_nonnegative_int(
        _field(raw_usage, "prompt_tokens", None), "prompt_tokens"
    )
    completion_tokens = _optional_nonnegative_int(
        _field(raw_usage, "completion_tokens", None), "completion_tokens"
    )
    raw_total = _field(raw_usage, "total_tokens", None)
    total_tokens = (
        prompt_tokens + completion_tokens
        if raw_total is None
        else _optional_nonnegative_int(raw_total, "total_tokens")
    )
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=_optional_nonnegative_int(
            _field(raw_usage, "prompt_cache_hit_tokens", None),
            "prompt_cache_hit_tokens",
        ),
        prompt_cache_miss_tokens=_optional_nonnegative_int(
            _field(raw_usage, "prompt_cache_miss_tokens", None),
            "prompt_cache_miss_tokens",
        ),
    )


def _normalize_tool_call(raw_call: Any) -> ToolCall:
    call_type = _field(raw_call, "type")
    if call_type != "function":
        raise AdapterProtocolError("only function tool calls are accepted")
    call_id = _field(raw_call, "id")
    if not isinstance(call_id, str) or not call_id:
        raise AdapterProtocolError("tool call id must be non-empty text")
    raw_function = _field(raw_call, "function")
    name = _field(raw_function, "name")
    arguments = _field(raw_function, "arguments")
    if not isinstance(name, str) or not name:
        raise AdapterProtocolError("tool function name must be non-empty text")
    if not isinstance(arguments, str):
        raise AdapterProtocolError("tool function arguments must be text")
    return ToolCall(id=call_id, type=call_type, name=name, arguments=arguments)


def _normalize_assistant(raw_message: Any) -> AssistantMessage:
    role = _field(raw_message, "role")
    if role != "assistant":
        raise AdapterProtocolError("chat completion message role must be assistant")
    content = _optional_text(_field(raw_message, "content", None), "content")
    reasoning_content = _optional_text(
        _field(raw_message, "reasoning_content", None), "reasoning_content"
    )
    raw_tool_calls = _field(raw_message, "tool_calls", None)
    if raw_tool_calls is None:
        tool_calls: tuple[ToolCall, ...] = ()
    else:
        if isinstance(raw_tool_calls, (str, bytes)) or not isinstance(raw_tool_calls, Sequence):
            raise AdapterProtocolError("tool_calls must be a sequence or null")
        tool_calls = tuple(_normalize_tool_call(call) for call in raw_tool_calls)
    return AssistantMessage(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
    )


def normalize_completion(raw_response: Any) -> ModelCompletion:
    """将一次 SDK 响应转换为与供应商无关的核心契约。"""

    # 第一步：要求恰好一个选择，并单独校验完成原因。
    choices = _field(raw_response, "choices")
    if isinstance(choices, (str, bytes)) or not isinstance(choices, Sequence):
        raise AdapterProtocolError("chat completion choices must be a sequence")
    if len(choices) != 1:
        raise AdapterProtocolError("chat completion must contain exactly one choice")
    choice = choices[0]
    finish_reason = _field(choice, "finish_reason")
    if not isinstance(finish_reason, str) or not finish_reason:
        raise AdapterProtocolError("finish_reason must be non-empty text")

    # 第二步：这些响应绝不进入历史；尤其不能解析或误执行被截断的半个工具调用。
    if finish_reason in _NON_HISTORICAL_FINISH_REASONS:
        assistant = AssistantMessage()
    elif finish_reason in {"stop", "tool_calls"}:
        assistant = _normalize_assistant(_field(choice, "message"))
    else:
        # 保留完成原因供核心决策表分类，但主动丢弃无法识别的消息结构。
        assistant = AssistantMessage()

    model = _field(raw_response, "model", None)
    if model is not None and not isinstance(model, str):
        raise AdapterProtocolError("response model must be text or null")
    system_fingerprint = _field(raw_response, "system_fingerprint", None)
    if system_fingerprint is not None and not isinstance(system_fingerprint, str):
        raise AdapterProtocolError("system_fingerprint must be text or null")

    # 第三步：规范化用量和可选元数据，生成不可变核心完成对象。
    return ModelCompletion(
        finish_reason=finish_reason,
        assistant=assistant,
        usage=_normalize_usage(_field(raw_response, "usage", None)),
        model=model,
        system_fingerprint=system_fingerprint,
    )


class DeepSeekAdapter:
    """一次处理一个请求的 DeepSeek Chat Completions 传输适配器。"""

    def __init__(
        self,
        client: Any | None = None,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """校验传输参数，并创建或接管一个禁用 SDK 自动重试的客户端。"""

        # 第一步：校验模型、令牌上限、超时及客户端与密钥的互斥关系。
        if not isinstance(model, str) or not model:
            raise ValueError("model must be non-empty text")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if not _is_finite_positive_number(timeout_seconds):
            raise ValueError("timeout_seconds must be positive and finite")
        if client is not None and api_key is not None:
            raise ValueError("provide either client or api_key, not both")
        # 第二步：只有未注入客户端时才创建 SDK 客户端，重试由核心状态机统一控制。
        if client is None:
            if not isinstance(api_key, str) or not api_key:
                raise ValueError("api_key is required when client is not provided")
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                max_retries=0,
                timeout=float(timeout_seconds),
            )

        self._client = client
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_seconds = float(timeout_seconds)
        self._close_lock = Lock()
        self._closed = False

    def close(self) -> None:
        """尽力且幂等地释放底层 SDK 客户端。

        没有可调用 ``close`` 的客户端无需适配器清理。清理异常会被主动抑制，防止
        ``finally`` 覆盖运行结果或暴露包含请求、凭据的异常文本；首次尝试后不再调用。
        """

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                close_client = getattr(self._client, "close", None)
                if callable(close_client):
                    close_client()
            except Exception:
                return

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        timeout_seconds: float | None = None,
    ) -> ModelCompletion:
        """发送一次非流式完成请求，并将 SDK 异常映射为稳定适配器错误。"""

        # 第一步：把调用方时限压缩到适配器上限，并防御性复制消息和工具定义。
        effective_timeout = self.timeout_seconds
        if timeout_seconds is not None:
            if not _is_finite_positive_number(timeout_seconds):
                raise ValueError("timeout_seconds must be positive and finite")
            effective_timeout = min(effective_timeout, float(timeout_seconds))

        request = {
            "model": self.model,
            "messages": deepcopy([dict(message) for message in messages]),
            "tools": deepcopy([dict(tool) for tool in tools]),
            "stream": False,
            "reasoning_effort": "high",
            "extra_body": {"thinking": {"type": "enabled"}},
            "max_tokens": self.max_tokens,
            "timeout": effective_timeout,
        }
        # 第二步：发送请求，只依据异常类型和状态码判断是否可重试，避免泄露响应正文。
        try:
            raw_response = self._client.chat.completions.create(**request)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if isinstance(status_code, bool) or not isinstance(status_code, int):
                status_code = None
            retryable = (
                isinstance(exc, (APIConnectionError, APITimeoutError))
                or status_code in {429, 500, 503}
            )
            raise AdapterRequestError(
                f"model request failed ({type(exc).__name__})",
                retryable=retryable,
                status_code=status_code,
            ) from exc
        # 第三步：严格规范化供应商响应后才交给核心状态机。
        return normalize_completion(raw_response)


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "DeepSeekAdapter",
    "normalize_completion",
]
