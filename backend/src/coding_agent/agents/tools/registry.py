"""注册工具模型并安全分发经过校验的工具调用。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from typing import Any

from coding_agent.agents.security import (
    CommandDecision,
    PermissionMode,
    PermissionPolicy,
    ToolApprovalRequest,
    Workspace,
    WorkspaceError,
)

from .command import run_command
from .contracts import (
    CancellationCheck,
    ToolConfirmation,
    ToolError,
    optional_integer,
    optional_number,
    optional_string,
    reject_unknown,
    require_string,
    validate_json_value,
)
from .filesystem import list_files, read_file, replace_text, write_file
from .search import search_text
from .schemas import TOOL_SCHEMAS, schemas_for_permission


ToolHandler = Callable[[dict[str, Any], float | None], dict[str, Any]]


class ToolRegistry:
    """包含六个固定工具、显式校验并返回 JSON 结果的注册表。"""

    def __init__(
        self,
        workspace: Workspace,
        *,
        confirm_action: ToolConfirmation | None = None,
        confirm_command: ToolConfirmation | None = None,
        cancel_check: CancellationCheck | None = None,
        permission_mode: PermissionMode | str | None = None,
        auto_approve: bool = False,
        max_read_chars: int = 20_000,
        max_file_bytes: int = 2_000_000,
        max_write_chars: int = 500_000,
        max_command_output_bytes: int = 12_000,
    ) -> None:
        """解析冻结权限，校验回调组合，并装配固定工具处理器。"""

        # 第一步：将旧 auto_approve 选项映射为权威权限模式，并拒绝冲突配置。
        if permission_mode is None:
            resolved_mode = (
                PermissionMode.WORKSPACE_FULL if auto_approve else PermissionMode.AGENT
            )
        else:
            resolved_mode = PermissionMode.parse(permission_mode)
            if auto_approve and resolved_mode is not PermissionMode.WORKSPACE_FULL:
                raise ValueError("auto_approve conflicts with the selected permission mode")
        if confirm_action is not None and confirm_command is not None:
            raise ValueError("pass confirm_action or confirm_command, not both")
        # 第二步：保存统一限制，并为五种固定工具绑定本工作区的隔离处理器。
        self.workspace = workspace
        self.confirm_action = confirm_action or confirm_command
        self.cancel_check = cancel_check
        self.permission_policy = PermissionPolicy(resolved_mode)
        # 旧版 CLI 和测试使用的兼容属性；其值现在由权威运行策略派生。
        self.auto_approve = self.permission_policy.mode is PermissionMode.WORKSPACE_FULL
        self.max_read_chars = max_read_chars
        self.max_file_bytes = max_file_bytes
        self.max_write_chars = max_write_chars
        self.max_command_output_bytes = max_command_output_bytes
        self._handlers: dict[str, ToolHandler] = {
            "list_files": lambda arguments, _timeout_seconds: list_files(workspace, arguments),
            "read_file": lambda arguments, _timeout_seconds: read_file(
                workspace,
                arguments,
                max_chars=max_read_chars,
                max_file_bytes=max_file_bytes,
            ),
            "search_text": lambda arguments, _timeout_seconds: search_text(
                workspace,
                arguments,
                max_file_bytes=max_file_bytes,
            ),
            "write_file": lambda arguments, _timeout_seconds: write_file(
                workspace,
                arguments,
                max_chars=max_write_chars,
            ),
            "replace_text": lambda arguments, _timeout_seconds: replace_text(
                workspace,
                arguments,
                max_file_bytes=max_file_bytes,
                max_new_chars=max_write_chars,
            ),
            "run_command": lambda arguments, timeout_seconds: run_command(
                workspace,
                arguments,
                confirm_action=self.confirm_action,
                cancel_check=cancel_check,
                permission_policy=self.permission_policy,
                max_output_bytes=max_command_output_bytes,
                timeout_cap_seconds=timeout_seconds,
            ),
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return schemas_for_permission(self.permission_policy)

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        """校验并执行一次工具调用，将所有结果收敛为统一 JSON 对象。"""

        # 第一步：校验工具可见性、参数对象和运行剩余时限。
        if not isinstance(name, str) or name not in self._handlers:
            return _serialize_error(ToolError("unknown_tool", "The requested tool is not registered."))
        if not self.permission_policy.allows_tool(name):
            return _serialize_error(
                ToolError(
                    "permission_denied",
                    f"The {name} tool is unavailable in {self.permission_policy.mode.value} mode.",
                )
            )
        if not isinstance(arguments, Mapping):
            return _serialize_error(ToolError("invalid_arguments", "Tool arguments must be a JSON object."))
        if timeout_seconds is not None:
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(float(timeout_seconds))
            ):
                return _serialize_error(
                    ToolError("invalid_timeout", "timeout_seconds must be a finite number or null.")
                )
            timeout_seconds = float(timeout_seconds)
            if timeout_seconds <= 0:
                return _serialize_error(
                    ToolError("wall_time_exceeded", "The run wall-time budget is exhausted.")
                )
        # 第二步：递归校验 JSON 值，完成必要审批，再调用对应处理器。
        try:
            normalized = dict(arguments)
            validate_json_value(normalized)
            self._confirm_tool_action(name, normalized)
            payload = self._handlers[name](normalized, timeout_seconds)
            response = {"ok": True, "data": payload.get("data", {}), "meta": payload.get("meta", {})}
            return json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        # 第三步：把预期领域错误和意外实现错误都封装在结构化工具边界内。
        except ToolError as exc:
            return _serialize_error(exc)
        except WorkspaceError as exc:
            return _serialize_error(ToolError(exc.code, exc.message, retryable=exc.retryable))
        except (OSError, UnicodeError) as exc:
            return _serialize_error(
                ToolError("tool_io_error", f"The tool failed with {type(exc).__name__}.", retryable=False)
            )
        except Exception as exc:  # 防御性边界：工具缺陷绝不能导致智能体循环崩溃。
            return _serialize_error(
                ToolError("internal_tool_error", f"Unexpected tool failure: {type(exc).__name__}.")
            )

    def _confirm_tool_action(self, name: str, arguments: Mapping[str, Any]) -> None:
        if self.permission_policy.tool_decision(name) is not CommandDecision.CONFIRM:
            return
        path = arguments.get("path")
        label = path if isinstance(path, str) and path else "工作区文件"
        verb = "写入" if name == "write_file" else "修改"
        request = ToolApprovalRequest(
            tool_name=name,
            action_summary=f"{verb} {label}",
            reason="当前权限要求在修改文件前确认。",
        )
        if self.confirm_action is None:
            raise ToolError("tool_confirmation_required", request.reason)
        try:
            approved = bool(self.confirm_action(request))
        except Exception as exc:
            raise ToolError(
                "tool_confirmation_failed", "The tool confirmation callback failed."
            ) from exc
        if not approved:
            raise ToolError("tool_rejected", "The user rejected the tool operation.")


def _serialize_error(error: ToolError) -> str:
    response: dict[str, Any] = {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
        },
    }
    if error.data is not None:
        response["data"] = error.data
    if error.meta is not None:
        response["meta"] = error.meta
    return json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


__all__ = [
    "ToolConfirmation",
    "TOOL_SCHEMAS",
    "ToolError",
    "ToolRegistry",
    "optional_integer",
    "optional_number",
    "optional_string",
    "reject_unknown",
    "require_string",
    "validate_json_value",
]
