"""Coding Agent 核心数据和主循环。"""

from coding_agent.agents.agent import DEFAULT_SYSTEM_PROMPT, Agent
from coding_agent.agents.config import AgentConfig
from coding_agent.agents.context import (
    AgentContext,
    AgentContextBuilder,
    MemoryReference,
    VisibleMessage,
    VisibleRole,
)
from coding_agent.agents.progress import RepeatObservation, RepeatedToolExchangeDetector
from coding_agent.agents.contracts import (
    AdapterProtocolError,
    AdapterRequestError,
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
    "AgentContext",
    "AgentContextBuilder",
    "AgentStatus",
    "AssistantMessage",
    "CompletionAdapter",
    "ModelCompletion",
    "MemoryReference",
    "RepeatObservation",
    "RepeatedToolExchangeDetector",
    "RunResult",
    "TerminationReason",
    "TokenUsage",
    "ToolCall",
    "ToolExecutor",
    "ToolRegistry",
    "TraceEmitter",
    "VisibleMessage",
    "VisibleRole",
]
