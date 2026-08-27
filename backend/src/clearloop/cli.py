"""Command-line composition root for ClearLoop.

This module deliberately contains no agent-loop or tool business logic.  It
parses configuration, wires the package boundaries together, and maps one run
to a stable process exit code.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, TextIO
from urllib.parse import urlsplit
from uuid import uuid4

from clearloop.core import Agent, AgentConfig, AgentStatus
from clearloop.diagnostics import NullTrace, TraceWriter
from clearloop.providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    DeepSeekAdapter,
)
from clearloop.security import CommandRequest, Workspace, WorkspaceError
from clearloop.tools import ToolRegistry


EXIT_SUCCESS = 0
EXIT_RUN_FAILED = 1
EXIT_CONFIGURATION = 2
EXIT_CANCELLED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clearloop",
        description="Run the ClearLoop local coding-agent loop in one workspace.",
    )
    parser.add_argument("task", help="Programming task given to the model.")
    parser.add_argument(
        "--workspace",
        default=".",
        metavar="PATH",
        help="Workspace root (default: current directory).",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model ID (default: {DEFAULT_MODEL}).")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"OpenAI-compatible API base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--max-model-calls", type=int, default=16)
    parser.add_argument("--max-tool-calls", type=int, default=40)
    parser.add_argument("--max-total-tokens", type=int, default=200_000)
    parser.add_argument("--wall-time", type=float, default=480.0, metavar="SECONDS")
    parser.add_argument(
        "--api-timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
    )
    parser.add_argument("--retries", type=int, default=3, help="Maximum transient retries per model turn.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Auto-approve CONFIRM commands; DENY commands remain denied.",
    )
    parser.add_argument("--no-trace", action="store_true", help="Disable local diagnostic JSONL output.")
    return parser


def _valid_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _trace_file(workspace: Workspace) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return workspace.root / ".clearloop-traces" / f"run-{timestamp}-{uuid4().hex[:8]}.jsonl"


def _confirmation_callback(
    *, input_func: Callable[[str], str], stream: TextIO
) -> Callable[[CommandRequest], bool]:
    def confirm(request: CommandRequest) -> bool:
        # JSON encoding prevents model-supplied control characters from being
        # interpreted by the terminal. This is interactive-only and is never
        # copied into the diagnostic trace.
        display = json.dumps(list(request.argv), ensure_ascii=False)
        stream.write(f"\nCommand requires approval: {display}\nReason: {request.reason}\n")
        stream.flush()
        try:
            answer = input_func("Approve this command? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().casefold() in {"y", "yes"}

    return confirm


def _safe_error(exc: BaseException, *, secret: str | None = None) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ")
    if secret:
        text = text.replace(secret, "***")
    rendered = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    return _terminal_safe(rendered)


def _terminal_safe(text: str) -> str:
    """Escape terminal control characters while preserving normal text layout."""

    rendered: list[str] = []
    for character in text:
        codepoint = ord(character)
        if character in {"\n", "\t"} or (
            codepoint >= 32 and codepoint != 127 and not 0x80 <= codepoint <= 0x9F
        ):
            rendered.append(character)
        else:
            rendered.append(f"\\u{codepoint:04x}")
    return "".join(rendered)


def run_cli(
    options: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    input_func: Callable[[str], str] = input,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    environment = os.environ if environ is None else environ
    api_key = environment.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        stderr.write("Configuration error: set DEEPSEEK_API_KEY in the local environment.\n")
        return EXIT_CONFIGURATION
    if not isinstance(options.task, str) or not options.task.strip():
        stderr.write("Configuration error: task must not be empty.\n")
        return EXIT_CONFIGURATION
    if len(options.task) > 100_000:
        stderr.write("Configuration error: task is too long.\n")
        return EXIT_CONFIGURATION
    if not _valid_base_url(options.base_url):
        stderr.write("Configuration error: --base-url must be an HTTP(S) URL without credentials.\n")
        return EXIT_CONFIGURATION

    try:
        workspace = Workspace(options.workspace)
        # The same allowlisted JSON event is appended to disk and shown on
        # stderr, so long API runs remain observable without leaking prompts,
        # reasoning, file contents, or command output.
        trace = (
            NullTrace()
            if options.no_trace
            else TraceWriter(_trace_file(workspace), stream=stderr)
        )
        adapter = DeepSeekAdapter(
            api_key=api_key,
            base_url=options.base_url,
            model=options.model,
            max_tokens=options.max_tokens,
            timeout_seconds=options.api_timeout,
        )
        registry = ToolRegistry(
            workspace,
            confirm_command=_confirmation_callback(input_func=input_func, stream=stderr),
            auto_approve=options.yes,
        )
        config = AgentConfig(
            max_model_calls=options.max_model_calls,
            max_tool_calls=options.max_tool_calls,
            max_total_tokens=options.max_total_tokens,
            wall_time_seconds=options.wall_time,
            api_timeout_seconds=options.api_timeout,
            max_transient_retries=options.retries,
        )
        result = Agent(adapter, registry, config=config, trace=trace).run(options.task)
    except KeyboardInterrupt:
        stderr.write("Cancelled by user.\n")
        return EXIT_CANCELLED
    except (ValueError, WorkspaceError) as exc:
        stderr.write(f"Configuration error: {_safe_error(exc, secret=api_key)}\n")
        return EXIT_CONFIGURATION
    except Exception as exc:
        stderr.write(f"Startup failure: {_safe_error(exc, secret=api_key)}\n")
        return EXIT_RUN_FAILED

    if result.final_content:
        stdout.write(_terminal_safe(result.final_content.rstrip()) + "\n")
    status = result.status.value if hasattr(result.status, "value") else str(result.status)
    reason = result.reason.value if hasattr(result.reason, "value") else str(result.reason)
    stderr.write(
        f"ClearLoop finished: status={status}, reason={reason}, "
        f"model_calls={result.model_calls}, tool_calls={result.tool_calls}, verified={result.verified}\n"
    )
    return EXIT_SUCCESS if result.status == AgentStatus.MODEL_FINISHED else EXIT_RUN_FAILED


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    return run_cli(options)


__all__ = [
    "EXIT_CANCELLED",
    "EXIT_CONFIGURATION",
    "EXIT_RUN_FAILED",
    "EXIT_SUCCESS",
    "build_parser",
    "main",
    "run_cli",
]
