"""Coding Agent 核心使用的数据类型和简单接口。"""

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
        """创建一条已经过脱敏的模型请求错误。

        :param message: 可安全写入日志或返回调用方的错误摘要。
        :param retryable: 当前错误是否属于允许重试的瞬时故障。
        :param status_code: 供应商返回的 HTTP 状态码；请求未到达服务时为 ``None``。
        """

        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ToolCall:
    """一次规范化的 Chat Completions 函数调用。"""

    # 供应商为本次工具调用生成的唯一标识。
    id: str
    # 要执行的本地工具名称。
    name: str
    # 模型输出的原始 JSON 参数字符串，尚未由工具层解析。
    arguments: str
    # OpenAI 兼容协议中的工具类型，目前固定为 function。
    type: str = "function"

    def as_message_dict(self) -> dict[str, Any]:
        """:return: 可原样写回模型消息历史的工具调用字典。"""

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
        """转换为可在下一轮请求中重放的助手消息。

        :return: 含普通内容、可选推理状态和工具调用的协议字典。
        """

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

    # 本次请求输入提示消耗的 Token 数。
    prompt_tokens: int = 0
    # 本次请求模型生成内容消耗的 Token 数。
    completion_tokens: int = 0
    # 本次请求输入与输出 Token 的合计值。
    total_tokens: int = 0
    # 输入提示命中供应商缓存的 Token 数。
    prompt_cache_hit_tokens: int = 0
    # 输入提示未命中供应商缓存的 Token 数。
    prompt_cache_miss_tokens: int = 0

    # 运算符重载，示例：usage1 + usage2 ---> usage1.__add__(usage2)
    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        """逐字段累加两次模型请求的用量。

        :param other: 要合并的另一份 Token 用量。
        :return: 各字段相加后得到的新 ``TokenUsage``，不会修改原对象。
        """

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
        """将各类 token 用量转换为普通字典。

        :return: 可用于事件、摘要或持久化的非负计数字典。
        """

        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "prompt_cache_hit_tokens": self.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": self.prompt_cache_miss_tokens,
        }


@dataclass(frozen=True, slots=True)
class ChangeCheckSummary:
    """文件修改与最近一次检查之间的关系。"""

    status: str = "no_changes"
    change_version: int = 0
    checked_version: int | None = None
    check_kind: str | None = None
    tool_sequence: int | None = None
    exit_code: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        """:return: 可安全写入事件和评测结果的普通字典。"""

        return {
            "status": self.status,
            "change_version": self.change_version,
            "checked_version": self.checked_version,
            "check_kind": self.check_kind,
            "tool_sequence": self.tool_sequence,
            "exit_code": self.exit_code,
        }


@dataclass(frozen=True, slots=True)
class ModelCompletion:
    """把一次大模型 API 调用的完整返回结果，整理成项目内部统一的数据结构。"""

    # 模型为什么停止生成
    finish_reason: str
    # 规范化后的助手正文、推理状态和工具调用。
    assistant: AssistantMessage = field(default_factory=AssistantMessage)
    # 本次供应商请求报告的 Token 用量。
    usage: TokenUsage = field(default_factory=TokenUsage)
    # 供应商实际使用的模型标识；未返回时为空。
    model: str | None = None
    # 供应商报告的后端配置指纹；不支持时为空。
    system_fingerprint: str | None = None


@runtime_checkable
class CompletionAdapter(Protocol):
    """模型客户端需要实现的方法。"""

    # 当前客户端实际请求的模型名称。
    model: str

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        timeout_seconds: float | None = None,
    ) -> ModelCompletion:
        """向模型提交完整消息历史和本轮可用工具。

        :param messages: 按协议顺序排列的系统、用户、助手和工具消息。
        :param tools: 本轮允许模型调用的 OpenAI 兼容函数工具 Schema。
        :param timeout_seconds: 本次网络请求允许等待的秒数；为空时使用客户端默认值。
        :return: 统一格式的模型回复。
        """

        ...


@runtime_checkable
class ToolExecutor(Protocol):
    """最小本地工具边界，实现返回 JSON 字符串。"""

    @property
    def schemas(self) -> Sequence[Mapping[str, Any]]:
        """返回当前运行允许模型看到的工具 Schema。

        :return: OpenAI 兼容函数工具定义序列。
        """

        ...

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        """执行一个经过注册的本地工具。

        :param name: 模型请求调用的工具名称。
        :param arguments: 已从严格 JSON 对象解析出的工具参数。
        :param timeout_seconds: 此次工具执行可使用的剩余秒数。
        :return: 供模型消费的规范 JSON 字符串。
        """

        ...


# 为兼容已有导入而保留的旧名称。
ToolRegistry = ToolExecutor


@runtime_checkable
class TraceEmitter(Protocol):
    """仅接受白名单字段的诊断事件接收器。"""

    def emit(self, event: str, /, **fields: Any) -> Any:
        """接收一条结构化诊断事件。

        :param event: 事件名称。
        :param fields: 事件携带的结构化白名单字段。
        :return: 接收器自定义返回值；调用方不会依赖它。
        """

        ...


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次智能体调用的不可变摘要。"""

    # 单次运行的唯一标识。
    run_id: str
    # 顶层终止状态。
    status: AgentStatus
    # 对终止状态作进一步说明的机器可读原因。
    reason: TerminationReason
    # 模型正常结束时面向用户的最终文本。
    final_content: str | None
    # 本次运行实际提交过的完整模型消息历史。
    messages: tuple[dict[str, Any], ...]
    # 实际发起的模型请求次数，包含瞬时错误重试。
    model_calls: int
    # 实际处理的工具调用数量。
    tool_calls: int
    # 整次运行累计的 Token 用量。
    usage: TokenUsage
    # 从开始到终止的墙钟耗时，单位为秒。
    duration_seconds: float
    # 外部验收状态；核心循环默认无法自行确认，值为 unknown。
    verified: str = "unknown"
    # 本轮文件修改是否被后续检查覆盖。
    change_check: ChangeCheckSummary = field(default_factory=ChangeCheckSummary)


__all__ = [
    "AdapterProtocolError",
    "AdapterRequestError",
    "AgentStatus",
    "AssistantMessage",
    "ChangeCheckSummary",
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
