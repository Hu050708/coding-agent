"""Coding Agent 命令行程序的组合入口。

本模块刻意不包含智能体循环或工具业务逻辑，只负责解析配置、连接各包边界，
并将一次运行结果映射为稳定的进程退出码。
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

from coding_agent.agents import Agent, AgentConfig, AgentStatus
from coding_agent.agents.diagnostics import NullTrace, TraceWriter
from coding_agent.agents.providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    DeepSeekAdapter,
)
from coding_agent.agents.security import CommandRequest, Workspace, WorkspaceError
from coding_agent.agents.tools import ToolRegistry


EXIT_SUCCESS = 0
EXIT_RUN_FAILED = 1
EXIT_CONFIGURATION = 2
EXIT_CANCELLED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coding-agent",
        description="在一个工作区中运行 Coding Agent 本地智能体循环。",
    )
    parser.add_argument("task", help="交给模型的编程任务。")
    parser.add_argument(
        "--workspace",
        default=".",
        metavar="PATH",
        help="工作区根目录（默认值：当前目录）。",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"模型 ID（默认值：{DEFAULT_MODEL}）。")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"兼容 OpenAI 的 API 基础 URL（默认值：{DEFAULT_BASE_URL}）。",
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
    parser.add_argument("--retries", type=int, default=3, help="每轮模型请求的最大瞬时错误重试次数。")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="自动批准需要确认的命令；禁止的命令仍会被拒绝。",
    )
    parser.add_argument("--no-trace", action="store_true", help="禁用本地诊断 JSONL 输出。")
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
    return workspace.root / ".coding-agent-traces" / f"run-{timestamp}-{uuid4().hex[:8]}.jsonl"


def _confirmation_callback(
    *, input_func: Callable[[str], str], stream: TextIO
) -> Callable[[CommandRequest], bool]:
    def confirm(request: CommandRequest) -> bool:
        # JSON 编码可防止模型提供的控制字符被终端解释；该文本仅用于交互，
        # 绝不会复制到诊断跟踪中。
        if request.argv:
            display = json.dumps(list(request.argv), ensure_ascii=False)
        else:
            display = request.action_summary
        stream.write(f"\nOperation requires approval: {display}\nReason: {request.reason}\n")
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
    """在保留普通文本布局的同时转义终端控制字符。"""

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
    """装配并执行一次 CLI 运行，将所有终态映射为稳定输出和退出码。"""

    # 第一步：在创建任何外部资源前校验密钥、任务和服务地址。
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
        # 第二步：同一个白名单 JSON 事件会写入磁盘并显示到 stderr，使长时间 API
        # 运行保持可观察，同时不泄露提示词、推理、文件内容或命令输出。
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
        # 第三步：完成边界装配后执行同步智能体，并统一捕获启动及配置错误。
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

    # 第四步：仅向 stdout 输出终端安全的最终内容，摘要和状态写入 stderr。
    if result.final_content:
        stdout.write(_terminal_safe(result.final_content.rstrip()) + "\n")
    status = result.status.value if hasattr(result.status, "value") else str(result.status)
    reason = result.reason.value if hasattr(result.reason, "value") else str(result.reason)
    stderr.write(
        f"Coding Agent finished: status={status}, reason={reason}, "
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
