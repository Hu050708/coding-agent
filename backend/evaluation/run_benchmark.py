"""运行三类 Coding Agent 任务并生成可复现评测报告。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Sequence

from .core.catalog import BACKEND_ROOT, TaskCatalog
from .core.runner import BenchmarkRunner


def build_parser() -> argparse.ArgumentParser:
    """构建评测命令行参数。"""

    catalog = TaskCatalog()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        action="append",
        choices=catalog.task_ids,
        dest="tasks",
        help="只运行指定任务；可重复使用。默认运行全部任务。",
    )
    parser.add_argument("--repeats", type=int, default=3, help="每个任务运行次数。")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--wall-time", type=float, default=None, metavar="SECONDS")
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """运行所选任务并根据是否全部通过返回进程状态。"""

    args = build_parser().parse_args(argv)
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        raise SystemExit("DEEPSEEK_API_KEY is not set in this process")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or BACKEND_ROOT / "tmp" / "benchmark-runs" / f"benchmark-{timestamp}"
    catalog = TaskCatalog()
    tasks = catalog.select(args.tasks)
    results = BenchmarkRunner(output).run(
        tasks,
        repeats=args.repeats,
        model=args.model,
        wall_time_seconds=args.wall_time,
    )
    successes = sum(result.classification == "success" for result in results)
    print(f"Benchmark complete: {successes}/{len(results)} verified trials")
    print(f"Report: {(output.resolve() / 'BENCHMARK_REPORT.md')}")
    return 0 if successes == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
