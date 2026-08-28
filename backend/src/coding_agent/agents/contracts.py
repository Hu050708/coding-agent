"""Coding Agent 核心层共享的供应商无关契约。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
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

    # 模型最终对外输出的普通内容
    content: str | None = None
    # 模型的推理相关内容
    reasoning_content: str | None = None
    # 模型要求调用哪些工具
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)

    def as_history_dict(self) -> dict[str, Any]:
        # DeepSeek V4 思考模式要求重放的工具调用助手消息携带非空 content 字段。
        # API 仍可能为该字段返回 null，因此仅在这一协议场景下，在写入历史前将其规范化为语义等价的空字符串。
        content = "" if self.tool_calls and self.content is None else self.content
        # 下面的代码就是组装JSON的
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

    # 运算符重载，示例：usage1 + usage2 ---> usage1.__add__(usage2)
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
    """把一次大模型 API 调用的完整返回结果，整理成项目内部统一的数据结构。"""

    # 模型为什么停止生成
    finish_reason: str
    assistant: AssistantMessage = field(default_factory=AssistantMessage)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str | None = None
    system_fingerprint: str | None = None


@runtime_checkable
class CompletionAdapter(Protocol):
    """规定所有“大模型适配器”必须长什么样的一份接口规范"""

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
