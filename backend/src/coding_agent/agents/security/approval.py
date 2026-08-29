"""定义工具执行边界使用的结构化审批请求。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .command_policy import CommandRequest


@dataclass(frozen=True, slots=True)
class ToolApprovalRequest:
    """工具层生成的一次用户可见审批请求。"""

    # 请求执行的注册工具名称。
    tool_name: str
    # 面向用户的简短操作摘要，避免包含完整敏感参数。
    action_summary: str
    # 当前操作需要人工确认的原因。
    reason: str
    # 命令工具使用的原始参数序列；文件工具保持为空。
    argv: tuple[str, ...] = ()
    # 命令工具的工作目录展示值。
    cwd: str = "."

    @classmethod
    def for_command(
        cls,
        request: CommandRequest,
        *,
        reason: str | None = None,
    ) -> "ToolApprovalRequest":
        """根据已分类命令构造脱敏程度适中的审批请求。

        :param request: 已解析可执行文件、目录和风险等级的命令请求。
        :param reason: 可选的权限层覆盖原因；省略时使用命令分类原因。
        :return: 可发布到 CLI 或 Web 审批通道的工具审批对象。
        """

        executable = Path(request.argv[0]).name or "command"
        argument_count = max(0, len(request.argv) - 1)
        return cls(
            tool_name="run_command",
            action_summary=f"{executable} ({argument_count} arguments)",
            reason=reason or request.reason,
            argv=request.argv,
            cwd=str(request.cwd),
        )


__all__ = ["ToolApprovalRequest"]
