"""叠加在不可变工作区边界之上的运行级权限策略。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .command_policy import CommandDecision


class PermissionMode(str, Enum):
    """为一次智能体运行冻结的三种用户可见权限模式。"""

    ASK = "ask"
    AGENT = "agent"
    WORKSPACE_FULL = "workspace_full"

    @classmethod
    def parse(cls, value: "PermissionMode | str") -> "PermissionMode":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise ValueError("permission mode must be ask, agent, or workspace_full")
        try:
            return cls(value.strip().casefold())
        except ValueError as exc:
            raise ValueError("permission mode must be ask, agent, or workspace_full") from exc


_WORKSPACE_TOOLS = frozenset(
    {
        "list_files",
        "read_file",
        "search_text",
        "write_file",
        "replace_text",
        "run_command",
    }
)
_WRITE_TOOLS = frozenset({"write_file", "replace_text"})


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    """一种不可变运行模式对应的服务端权威能力。

    这是应用策略而非操作系统沙箱，工作区解析器和命令分类器仍是必需的底层防线。
    """

    mode: PermissionMode = PermissionMode.AGENT

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", PermissionMode.parse(self.mode))

    @property
    def tool_names(self) -> frozenset[str]:
        return _WORKSPACE_TOOLS

    def allows_tool(self, name: str) -> bool:
        return isinstance(name, str) and name in self.tool_names

    def tool_decision(self, name: str) -> CommandDecision:
        if name not in self.tool_names:
            return CommandDecision.DENY
        if self.mode is PermissionMode.ASK and name in _WRITE_TOOLS:
            return CommandDecision.CONFIRM
        return CommandDecision.ALLOW

    def command_decision(self, classified: CommandDecision) -> CommandDecision:
        """综合命令分类结果与运行冻结的权限。"""

        if classified is CommandDecision.DENY:
            return CommandDecision.DENY
        if self.mode is PermissionMode.ASK:
            return CommandDecision.CONFIRM
        if self.mode is PermissionMode.WORKSPACE_FULL:
            return CommandDecision.ALLOW
        return classified

    def command_approval_reason(self, classified_reason: str) -> str:
        if self.mode is PermissionMode.ASK:
            return "当前权限要求在执行命令前确认。"
        return classified_reason


__all__ = ["PermissionMode", "PermissionPolicy"]
