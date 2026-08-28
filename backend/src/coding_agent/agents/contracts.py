"""Coding Agent 核心层共享的供应商无关契约。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Protocol, runtime_checkable


class AgentStatus(str, Enum):
    """一次调用的终止状态。"""

    MODEL_FINISHED = "model_finished"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class TerminationReason(str, Enum):
    """终止状态对应的机器可读原因。"""

    MODEL_FINAL = "model_final"
    MAX_MODEL_CALLS = "max_model_calls"
    MAX_TOOL_CALLS = "max_tool_calls"
    TOKEN_BUDGET_EXCEEDED = "token_budget_exceeded"
    WALL_TIME_EXCEEDED = "wall_time_exceeded"
    API_FATAL_ERROR = "api_fatal_error"
    CONTENT_FILTERED = "content_filtered"
    TRUNCATED_RESPONSE = "truncated_response"
    PROTOCOL_ERROR = "protocol_error"
    USER_CANCELLED = "user_cancelled"
    INTERNAL_INVARIANT_VIOLATION = "internal_invariant_violation"


class AdapterProtocolError(RuntimeError):
    """供应商返回了无法写入消息历史的响应。"""


class AdapterRequestError(RuntimeError):
    """经过脱敏的供应商请求失败。

    原始异常仍可通过 ``__cause__`` 用于本地调试，但消息会主动排除可能包含敏感
    内容的响应正文和请求数据。
    """

    def __init__(
        self,
        message: str = "model request failed",
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ToolCall:
    """一次规范化的 Chat Completions 函数调用。"""

    id: str
    name: str
    arguments: str
    type: str = "function"

    def as_message_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """携带 DeepSeek 推理状态且与供应商无关的助手消息。"""

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)

    def as_history_dict(self) -> dict[str, Any]:
        # DeepSeek V4 思考模式要求重放的工具调用助手消息携带非空 content 字段。
        # API 仍可能为该字段返回 null，因此仅在这一协议场景下，在写入历史前
        # 将其规范化为语义等价的空字符串。
        content = "" if self.tool_calls and self.content is None else self.content
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if self.reasoning_content is not None:
            message["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            message["tool_calls"] = [call.as_message_dict() for call in self.tool_calls]
        return message


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """预算和安全诊断所需的最小用量字段集。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            prompt_cache_hit_tokens=(
                self.prompt_cache_hit_tokens + other.prompt_cache_hit_tokens
            ),
            prompt_cache_miss_tokens=(
                self.prompt_cache_miss_tokens + other.prompt_cache_miss_tokens
            ),
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "prompt_cache_hit_tokens": self.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": self.prompt_cache_miss_tokens,
        }


@dataclass(frozen=True, slots=True)
class ModelCompletion:
    """一次非流式 Chat Completions 请求的规范化结果。"""

    finish_reason: str
    assistant: AssistantMessage = field(default_factory=AssistantMessage)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str | None = None
    system_fingerprint: str | None = None


@runtime_checkable
class CompletionAdapter(Protocol):
    """供智能体状态机调用的模型供应商边界。"""

    model: str

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        timeout_seconds: float | None = None,
    ) -> ModelCompletion: ...


@runtime_checkable
class ToolExecutor(Protocol):
    """最小本地工具边界，实现返回 JSON 字符串。"""

    @property
    def schemas(self) -> Sequence[Mapping[str, Any]]: ...

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> str: ...


# 为兼容已有导入而保留的旧名称。
ToolRegistry = ToolExecutor


@runtime_checkable
class TraceEmitter(Protocol):
    """仅接受白名单字段的诊断事件接收器。"""

    def emit(self, event: str, /, **fields: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """一次调用使用的硬预算和有界重试策略。"""

    max_model_calls: int = 16
    max_tool_calls: int = 40
    max_total_tokens: int = 200_000
    wall_time_seconds: float = 480.0
    api_timeout_seconds: float = 60.0
    max_transient_retries: int = 3
    retry_base_seconds: float = 0.25
    retry_jitter_seconds: float = 0.1
    max_task_chars: int = 100_000
    max_prior_messages: int = 48
    max_prior_chars: int = 80_000
    repeat_warning_threshold: int = 3
    max_repeat_fingerprints: int = 128

    def __post_init__(self) -> None:
        """校验所有预算类型、正负性和有限性，阻止无界配置进入状态机。"""

        # 第一步：统一识别排除布尔值的有限数值。
        def finite_number(value: Any) -> bool:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            try:
                return math.isfinite(value)
            except OverflowError:
                return False

        # 第二步：分别校验正整数预算、正数时限及非负重试参数。
        positive_ints = {
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_total_tokens": self.max_total_tokens,
            "max_task_chars": self.max_task_chars,
            "max_prior_messages": self.max_prior_messages,
            "max_prior_chars": self.max_prior_chars,
            "max_repeat_fingerprints": self.max_repeat_fingerprints,
        }
        for name, value in positive_ints.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.repeat_warning_threshold, bool)
            or not isinstance(self.repeat_warning_threshold, int)
            or self.repeat_warning_threshold < 2
        ):
            raise ValueError("repeat_warning_threshold must be an integer greater than one")
        positive_numbers = {
            "wall_time_seconds": self.wall_time_seconds,
            "api_timeout_seconds": self.api_timeout_seconds,
        }
        for name, value in positive_numbers.items():
            if not finite_number(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if (
            isinstance(self.max_transient_retries, bool)
            or not isinstance(self.max_transient_retries, int)
            or self.max_transient_retries < 0
        ):
            raise ValueError("max_transient_retries must be a non-negative integer")
        for name, value in {
            "retry_base_seconds": self.retry_base_seconds,
            "retry_jitter_seconds": self.retry_jitter_seconds,
        }.items():
            if not finite_number(value) or value < 0:
                raise ValueError(f"{name} must be non-negative and finite")


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次智能体调用的不可变摘要。"""

    run_id: str
    status: AgentStatus
    reason: TerminationReason
    final_content: str | None
    messages: tuple[dict[str, Any], ...]
    model_calls: int
    tool_calls: int
    usage: TokenUsage
    duration_seconds: float
    verified: str = "unknown"


__all__ = [
    "AdapterProtocolError",
    "AdapterRequestError",
    "AgentConfig",
    "AgentStatus",
    "AssistantMessage",
    "CompletionAdapter",
    "ModelCompletion",
    "RunResult",
    "TerminationReason",
    "TokenUsage",
    "ToolCall",
    "ToolExecutor",
    "ToolRegistry",
    "TraceEmitter",
]
