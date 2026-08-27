"""Create and evaluate one fresh, real-API Coding Agent demo trial.

The script never overwrites or deletes a candidate directory.  It invokes the
public CLI in a child process, then runs the independent evaluator.  The API key
is inherited through the environment and is never placed in argv or output.
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "tmp" / "demo-runs" / f"trial-{stamp}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None, help="new candidate directory")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--wall-time", type=float, default=480.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
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

    agent_command = [
        sys.executable,
        "-m",
        "coding-agent",
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
