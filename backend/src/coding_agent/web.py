"""Command-line entry point for the local Coding Agent Web API."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from coding_agent.main import serve


def build_parser() -> argparse.ArgumentParser:
    """Build the deliberately small server command-line interface."""

    return argparse.ArgumentParser(
        prog="coding-agent-web",
        description=(
            "Start the loopback-only Coding Agent Web API. "
            "Configuration is read from environment variables and the project .env file."
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Validate command-line arguments, then start the supported server."""

    build_parser().parse_args(argv)
    serve()


if __name__ == "__main__":
    main()


__all__ = ["build_parser", "main"]
