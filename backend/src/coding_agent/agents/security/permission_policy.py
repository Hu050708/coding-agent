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
        """将枚举或用户输入文本规范化为权限模式。

        :param value: 已有权限枚举或不区分大小写的模式字符串。
        :return: 对应的 ``PermissionMode``。
        :raises ValueError: 输入类型或模式名称不受支持。
        """

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
        "make_directory",
        "write_file",
        "replace_text",
        "delete_file",
        "run_command",
    }
)
_WRITE_TOOLS = frozenset({"make_directory", "write_file", "replace_text", "delete_file"})
_DESTRUCTIVE_TOOLS = frozenset({"delete_file"})


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    """一种不可变运行模式对应的服务端权威能力。

    这是应用策略而非操作系统沙箱，工作区解析器和命令分类器仍是必需的底层防线。
    """

    # 本次运行冻结的用户可见权限模式。
    mode: PermissionMode = PermissionMode.AGENT

    def __post_init__(self) -> None:
        """把字符串或枚举模式规范化为 ``PermissionMode``。"""

        object.__setattr__(self, "mode", PermissionMode.parse(self.mode))

    @property
    def tool_names(self) -> frozenset[str]:
        """返回服务端固定注册的工作区工具名称。

        :return: 不可变工具名称集合。
        """

        return _WORKSPACE_TOOLS

    def allows_tool(self, name: str) -> bool:
        """判断工具名称是否属于服务端固定能力集合。

        :param name: 模型请求的工具名称。
        :return: 名称为已注册工作区工具时返回 ``True``。
        """

        return isinstance(name, str) and name in self.tool_names

    def tool_decision(self, name: str) -> CommandDecision:
        """计算非命令工具在当前模式下的执行决定。

        :param name: 模型请求的工具名称。
        :return: 未知工具拒绝；删除默认确认；询问模式下所有修改工具确认。
        """

        if name not in self.tool_names:
            return CommandDecision.DENY
        if name in _DESTRUCTIVE_TOOLS and self.mode is not PermissionMode.WORKSPACE_FULL:
            return CommandDecision.CONFIRM
        if self.mode is PermissionMode.ASK and name in _WRITE_TOOLS:
            return CommandDecision.CONFIRM
        return CommandDecision.ALLOW

    def command_decision(self, classified: CommandDecision) -> CommandDecision:
        """综合命令分类结果与运行冻结的权限。

        :param classified: 底层命令分类器给出的不可变风险决定。
        :return: 当前权限模式进一步收紧或放宽确认步骤后的最终决定。
        """

        if classified is CommandDecision.DENY:
            return CommandDecision.DENY
        if self.mode is PermissionMode.ASK:
            return CommandDecision.CONFIRM
        if self.mode is PermissionMode.WORKSPACE_FULL:
            return CommandDecision.ALLOW
        return classified

    def command_approval_reason(self, classified_reason: str) -> str:
        """生成最终展示给用户的命令审批原因。

        :param classified_reason: 命令分类器提供的原始原因。
        :return: 询问模式的统一原因，或原始分类原因。
        """

        if self.mode is PermissionMode.ASK:
            return "当前权限要求在执行命令前确认。"
        return classified_reason


__all__ = ["PermissionMode", "PermissionPolicy"]
