"""创建并评估一次使用真实 API 的全新 Coding Agent 演示试验。

脚本绝不覆盖或删除候选目录；它先在子进程中调用公共 CLI，再运行独立评测器。
API 密钥仅通过环境继承，绝不会出现在命令参数或输出中。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE = PROJECT_ROOT / "examples" / "date_boundary_bug"
EVALUATOR = PROJECT_ROOT / "evaluation" / "verify_date_boundary.py"


def _default_output() -> Path:
    """生成带 UTC 时间戳的默认试验输出目录。

    :return: ``backend/tmp/demo-runs`` 下的新候选目录路径。
    """

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "tmp" / "demo-runs" / f"trial-{stamp}"


def build_parser() -> argparse.ArgumentParser:
    """构建真实 API 演示试验的命令行解析器。

    :return: 支持输出目录、模型和墙钟上限的参数解析器。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None, help="新候选目录")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--wall-time", type=float, default=480.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """复制基线、运行智能体、独立验收候选结果并写出试验摘要。

    :param argv: 可选命令行参数；None 表示读取当前进程参数。
    :return: 智能体和独立评测均成功时为 0，配置错误为 2，其余失败为 1。
    """

    # 第一步：校验真实 API 凭据和全新输出路径，再复制只读基线作为候选目录。
    args = build_parser().parse_args(argv)
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        print("DEEPSEEK_API_KEY is not set in this process.", file=sys.stderr)
        return 2

    output = (args.output or _default_output()).resolve()
    if output.exists():
        print(f"Refusing to overwrite existing output: {output}", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(BASELINE, output, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    task = (output / "TASK.md").read_text(encoding="utf-8")

    # 第二步：在外层超时保护下运行智能体，任务文本仅作为单个参数传递。
    agent_command = [
        sys.executable,
        "-m",
        "coding_agent",
        "--workspace",
        os.fspath(output),
        "--model",
        args.model,
        "--wall-time",
        str(args.wall_time),
        "--yes",
        task,
    ]
    try:
        agent_run = subprocess.run(
            agent_command,
            cwd=PROJECT_ROOT,
            env=os.environ.copy(),
            timeout=args.wall_time + 30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("Coding Agent child process exceeded the outer demo timeout.", file=sys.stderr)
        return 1

    # 第三步：移除所有 API 密钥后启动独立评测器，避免候选测试接触凭据。
    evaluator_environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() != "DEEPSEEK_API_KEY" and not name.upper().endswith("_API_KEY")
    }
    evaluator_run = subprocess.run(
        [sys.executable, os.fspath(EVALUATOR), os.fspath(output)],
        cwd=PROJECT_ROOT,
        env=evaluator_environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if evaluator_run.stdout:
        print(evaluator_run.stdout.rstrip())
    if evaluator_run.stderr:
        print(evaluator_run.stderr.rstrip(), file=sys.stderr)

    # 第四步：仅当智能体和评测器都成功时判定通过，并写出机器可读摘要。
    verified = agent_run.returncode == 0 and evaluator_run.returncode == 0
    result_path = output.parent / f"{output.name}-result.json"
    result_path.write_text(
        json.dumps(
            {
                "candidate": os.fspath(output),
                "model": args.model,
                "agent_exit_code": agent_run.returncode,
                "evaluator_exit_code": evaluator_run.returncode,
                "verified": verified,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Trial result: {result_path}", file=sys.stderr)
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
