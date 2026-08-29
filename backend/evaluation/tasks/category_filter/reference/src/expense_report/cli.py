"""支持重复类别参数的支出汇总命令行入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .service import summarize_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="汇总 JSONL 支出记录")
    parser.add_argument("expense_file", type=Path)
    parser.add_argument("--category", action="append", dest="categories")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = summarize_file(
            args.expense_file,
            categories=set(args.categories) if args.categories is not None else None,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
