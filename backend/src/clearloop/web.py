"""Command-line entry point for the local ClearLoop Web API."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from clearloop.main import serve


def build_parser() -> argparse.ArgumentParser:
    """Build the deliberately small server command-line interface."""

    return argparse.ArgumentParser(
        prog="clearloop-web",
        description=(
            "Start the loopback-only ClearLoop Web API. "
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
