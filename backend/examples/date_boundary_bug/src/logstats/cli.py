"""logstats 示例程序的命令行接口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .service import summarize_file


def build_parser() -> argparse.ArgumentParser:
    """构建日志统计示例的命令行解析器。

    :return: 支持日志路径和可选起止日期的参数解析器。
    """

    parser = argparse.ArgumentParser(description="汇总带时间戳的 JSONL 日志")
    parser.add_argument("log_file", type=Path, help="JSONL 日志文件路径")
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数、汇总日志并输出 JSON。

    :param argv: 可选命令行参数；None 表示读取当前进程参数。
    :return: 成功时返回 0；参数或数据错误由 argparse 终止进程。
    """

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
