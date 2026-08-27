"""Provider-independent contracts shared by the ClearLoop core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Protocol, runtime_checkable


class AgentStatus(str, Enum):
    """Terminal state of one invocation."""

    MODEL_FINISHED = "model_finished"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class TerminationReason(str, Enum):
    """Machine-readable reason for a terminal state."""

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
    """The provider returned a response that cannot enter message history."""


class AdapterRequestError(RuntimeError):
    """A sanitized provider request failure.

    The original exception remains available through ``__cause__`` for local
    debugging, but the message intentionally excludes response bodies and
    request data that could contain sensitive content.
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
    """One canonical Chat Completions function call."""

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
    """Provider-independent assistant message with DeepSeek reasoning state."""

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)

    def as_history_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.reasoning_content is not None:
            message["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            message["tool_calls"] = [call.as_message_dict() for call in self.tool_calls]
        return message


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """The small usage subset needed for budgets and safe diagnostics."""

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
    """Normalized result of one non-streaming Chat Completions request."""

    finish_reason: str
    assistant: AssistantMessage = field(default_factory=AssistantMessage)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str | None = None
    system_fingerprint: str | None = None


@runtime_checkable
class CompletionAdapter(Protocol):
    """Provider boundary consumed by the agent state machine."""

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
    """Minimal local-tool boundary; implementations return JSON strings."""

    @property
    def schemas(self) -> Sequence[Mapping[str, Any]]: ...

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> str: ...


# Backward-compatible name retained for existing imports.
ToolRegistry = ToolExecutor


@runtime_checkable
class TraceEmitter(Protocol):
    """Allowlist-only diagnostic event sink."""

    def emit(self, event: str, /, **fields: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Hard budgets and bounded retry behavior for one invocation."""

    max_model_calls: int = 16
    max_tool_calls: int = 40
    max_total_tokens: int = 200_000
    wall_time_seconds: float = 480.0
    api_timeout_seconds: float = 60.0
    max_transient_retries: int = 3
    retry_base_seconds: float = 0.25
    retry_jitter_seconds: float = 0.1

    def __post_init__(self) -> None:
        def finite_number(value: Any) -> bool:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            try:
                return math.isfinite(value)
            except OverflowError:
                return False

        positive_ints = {
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_total_tokens": self.max_total_tokens,
        }
        for name, value in positive_ints.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
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
    """Immutable summary of one agent invocation."""

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
