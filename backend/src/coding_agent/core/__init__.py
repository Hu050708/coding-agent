"""Provider-independent Coding Agent contracts and state machine."""

from coding_agent.core.agent import DEFAULT_SYSTEM_PROMPT, Agent
from coding_agent.core.contracts import (
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
