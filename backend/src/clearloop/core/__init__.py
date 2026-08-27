"""Provider-independent ClearLoop contracts and state machine."""

from clearloop.core.agent import DEFAULT_SYSTEM_PROMPT, Agent
from clearloop.core.contracts import (
    AdapterProtocolError,
    AdapterRequestError,
    AgentConfig,
    AgentStatus,
    AssistantMessage,
    CompletionAdapter,
    ModelCompletion,
    RunResult,
    TerminationReason,
    TokenUsage,
    ToolCall,
    ToolExecutor,
    ToolRegistry,
    TraceEmitter,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "AdapterProtocolError",
    "AdapterRequestError",
    "Agent",
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
