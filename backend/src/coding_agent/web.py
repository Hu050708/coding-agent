"""本地 Coding Agent Web API 的命令行入口。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from coding_agent.main import serve


def build_parser() -> argparse.ArgumentParser:
    """构建刻意精简的服务端命令行接口。"""

    return argparse.ArgumentParser(
        prog="coding-agent-web",
        description=(
            "启动仅监听回环地址的 Coding Agent Web API。"
            "配置从环境变量和项目的 .env 文件中读取。"
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    """校验命令行参数后启动受支持的服务器。"""

    build_parser().parse_args(argv)
    serve()


if __name__ == "__main__":
    main()


__all__ = ["build_parser", "main"]
