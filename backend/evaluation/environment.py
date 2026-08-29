"""评测子进程共用的环境变量处理。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


_SECRET_SUFFIXES = ("_API_KEY", "_ACCESS_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD")
_SECRET_NAMES = {
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
}


def without_secrets(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """复制环境变量并移除常见凭据名称。"""

    environment = os.environ if source is None else source
    return {
        name: value
        for name, value in environment.items()
        if name.upper() not in _SECRET_NAMES
        and not name.upper().endswith(_SECRET_SUFFIXES)
    }


def candidate_environment(
    candidate: Path,
    *,
    additions: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """构建只从候选 ``src`` 导入代码且不含 API 凭据的环境。"""

    environment = without_secrets()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONPATH"] = str(candidate / "src")
    environment.pop("PYTHONHOME", None)
    if additions:
        environment.update(additions)
    return environment


__all__ = ["candidate_environment", "without_secrets"]
