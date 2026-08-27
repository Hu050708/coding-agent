"""Command-line interface for logstats."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .service import summarize_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize timestamped JSONL logs")
    parser.add_argument("log_file", type=Path, help="path to a JSONL log file")
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = summarize_file(
            args.log_file,
            from_date=args.from_date,
            to_date=args.to_date,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
