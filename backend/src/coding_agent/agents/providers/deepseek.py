"""基于官方 OpenAI Python 客户端实现 DeepSeek Chat Completions 适配器。"""

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
    """判断输入是否为非布尔类型的有限正数。

    :param value: 待校验的任意值。
    :return: 输入为大于零的有限整数或浮点数时返回 ``True``。
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _field(value: Any, name: str, default: Any = _MISSING) -> Any:
    """统一读取 SDK 对象属性或字典字段。

    :param value: SDK 数据对象或字段映射。
    :param name: 要读取的属性或键名称。
    :param default: 字段缺失时返回的默认值；省略表示字段必须存在。
    :return: 读取到的字段值或显式默认值。
    :raises AdapterProtocolError: 必填字段不存在。
    """

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
    """校验供应商可空文本字段。

    :param value: 待校验的字段值。
    :param field_name: 用于错误消息的协议字段名称。
    :return: 原字符串或 ``None``。
    :raises AdapterProtocolError: 非空值不是字符串。
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterProtocolError(f"{field_name} must be text or null")
    return value


def _optional_nonnegative_int(value: Any, field_name: str) -> int:
    """校验可缺省的非负整数字段。

    :param value: 待校验的用量字段，``None`` 按零处理。
    :param field_name: 用于错误消息的用量字段名称。
    :return: 合法非负整数。
    :raises AdapterProtocolError: 值为布尔值、负数或非整数。
    """

    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterProtocolError(f"usage.{field_name} must be a non-negative integer")
    return value


def _normalize_usage(raw_usage: Any) -> TokenUsage:
    """把供应商用量字段转换为稳定的核心 TokenUsage。

    :param raw_usage: SDK 返回的用量对象、映射或 ``None``。
    :return: 缺失字段已补零的核心 Token 用量对象。
    :raises AdapterProtocolError: 供应商返回了非法用量字段。
    """

    if raw_usage is None:
        return TokenUsage()
    # 第一步：读取提示词和输出令牌；缺失字段按零处理。
    prompt_tokens = _optional_nonnegative_int(
        _field(raw_usage, "prompt_tokens", None), "prompt_tokens"
    )
    completion_tokens = _optional_nonnegative_int(
        _field(raw_usage, "completion_tokens", None), "completion_tokens"
    )
    # 第二步：供应商未给总量时由两个分项确定性计算。
    raw_total = _field(raw_usage, "total_tokens", None)
    total_tokens = (
        prompt_tokens + completion_tokens
        if raw_total is None
        else _optional_nonnegative_int(raw_total, "total_tokens")
    )
    # 第三步：补齐 DeepSeek 提供的缓存命中与未命中统计。
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
    """把一条供应商函数调用转换为核心工具调用。

    :param raw_call: SDK 返回的单条工具调用对象或映射。
    :return: 字段完整且不可变的 ``ToolCall``。
    :raises AdapterProtocolError: 类型、调用 ID、函数名或参数字段不合法。
    """

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
    """规范化助手正文、思考内容和函数工具调用。

    :param raw_message: SDK 返回的助手消息对象或映射。
    :return: 与供应商无关的不可变助手消息。
    :raises AdapterProtocolError: 角色、文本或工具调用集合不符合协议。
    """

    # 第一步：确认消息角色，并读取两个可选文本字段。
    role = _field(raw_message, "role")
    if role != "assistant":
        raise AdapterProtocolError("chat completion message role must be assistant")
    content = _optional_text(_field(raw_message, "content", None), "content")
    reasoning_content = _optional_text(
        _field(raw_message, "reasoning_content", None), "reasoning_content"
    )
    # 第二步：工具调用必须是序列，并逐项转换为核心 ToolCall。
    raw_tool_calls = _field(raw_message, "tool_calls", None)
    if raw_tool_calls is None:
        tool_calls: tuple[ToolCall, ...] = ()
    else:
        if isinstance(raw_tool_calls, (str, bytes)) or not isinstance(raw_tool_calls, Sequence):
            raise AdapterProtocolError("tool_calls must be a sequence or null")
        tool_calls = tuple(_normalize_tool_call(call) for call in raw_tool_calls)
    # 第三步：构造不可变消息，后续由 Agent 决定写入历史或执行工具。
    return AssistantMessage(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
    )


def normalize_completion(raw_response: Any) -> ModelCompletion:
    """将一次 SDK 响应转换为与供应商无关的核心契约。

    :param raw_response: OpenAI SDK 返回的 Chat Completions 响应对象或映射。
    :return: 经过严格字段校验的 ``ModelCompletion``。
    :raises AdapterProtocolError: 响应选择数、完成原因或消息字段不合法。
    """

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
        """校验传输参数，并创建或接管一个禁用 SDK 自动重试的客户端。

        :param client: 可选的兼容 OpenAI 客户端，主要供测试或自定义传输注入。
        :param api_key: 创建默认客户端时使用的 DeepSeek API 密钥。
        :param base_url: OpenAI 兼容接口的基础 URL。
        :param model: 每次请求使用的模型标识。
        :param max_tokens: 单次模型响应允许生成的最大 Token 数。
        :param timeout_seconds: 适配器允许单次请求等待的最长秒数。
        :raises ValueError: 参数非法，或同时提供 ``client`` 与 ``api_key``。
        """

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

        # 实际承担 HTTP 请求的 SDK 客户端。
        self._client = client
        # 对外报告并随每次请求发送的模型标识。
        self.model = model
        # 单次补全允许生成的 Token 上限。
        self.max_tokens = max_tokens
        # 适配器级请求超时上限，调用方只能进一步缩短。
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
        """发送一次非流式完成请求，并将 SDK 异常映射为稳定适配器错误。

        :param messages: 本轮完整且按协议排序的消息历史。
        :param tools: 本轮允许模型调用的函数工具 Schema。
        :param timeout_seconds: 核心状态机计算出的剩余请求时间；不能放宽适配器上限。
        :return: 严格规范化后的模型完成结果。
        :raises ValueError: 调用方超时值不是有限正数。
        :raises AdapterRequestError: 网络、超时或供应商 HTTP 请求失败。
        :raises AdapterProtocolError: 供应商响应不满足核心协议。
        """

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
