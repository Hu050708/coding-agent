"""定义工具执行边界使用的结构化审批请求。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .command_policy import CommandRequest


@dataclass(frozen=True, slots=True)
class ToolApprovalRequest:
    """工具层生成的一次用户可见审批请求。"""

    tool_name: str
    action_summary: str
    reason: str
    argv: tuple[str, ...] = ()
    cwd: str = "."

    @classmethod
    def for_command(
        cls,
        request: CommandRequest,
        *,
        reason: str | None = None,
    ) -> "ToolApprovalRequest":
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
