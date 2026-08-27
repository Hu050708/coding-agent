from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable, Mapping
from typing import Any

from coding_agent.security.workspace import Workspace, WorkspaceError

from .command import run_command
from .contracts import (
    CancellationCheck,
    CommandConfirmation,
    ToolError,
    optional_integer,
    optional_number,
    optional_string,
    reject_unknown,
    require_string,
    validate_json_value,
)
from .filesystem import list_files, read_file, replace_text, write_file
from .schemas import TOOL_SCHEMAS


ToolHandler = Callable[[dict[str, Any], float | None], dict[str, Any]]


class ToolRegistry:
    """Fixed five-tool registry with explicit validation and JSON results."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        confirm_command: CommandConfirmation | None = None,
        cancel_check: CancellationCheck | None = None,
        auto_approve: bool = False,
        max_read_chars: int = 20_000,
        max_file_bytes: int = 2_000_000,
        max_write_chars: int = 500_000,
        max_command_output_bytes: int = 12_000,
    ) -> None:
        self.workspace = workspace
        self.confirm_command = confirm_command
        self.cancel_check = cancel_check
        self.auto_approve = auto_approve
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
                confirm_command=confirm_command,
                cancel_check=cancel_check,
                auto_approve=auto_approve,
                max_output_bytes=max_command_output_bytes,
                timeout_cap_seconds=timeout_seconds,
            ),
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return copy.deepcopy(TOOL_SCHEMAS)

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        if not isinstance(name, str) or name not in self._handlers:
            return _serialize_error(ToolError("unknown_tool", "The requested tool is not registered."))
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
        try:
            normalized = dict(arguments)
            validate_json_value(normalized)
            payload = self._handlers[name](normalized, timeout_seconds)
            response = {"ok": True, "data": payload.get("data", {}), "meta": payload.get("meta", {})}
            return json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except ToolError as exc:
            return _serialize_error(exc)
        except WorkspaceError as exc:
            return _serialize_error(ToolError(exc.code, exc.message, retryable=exc.retryable))
        except (OSError, UnicodeError) as exc:
            return _serialize_error(
                ToolError("tool_io_error", f"The tool failed with {type(exc).__name__}.", retryable=False)
            )
        except Exception as exc:  # Defensive boundary: never crash the agent loop on a tool bug.
            return _serialize_error(
                ToolError("internal_tool_error", f"Unexpected tool failure: {type(exc).__name__}.")
            )


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
    "CommandConfirmation",
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
