"""正确保留 falsey 值的分层配置加载器。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, TypeVar

from .models import Settings


T = TypeVar("T")


def _choose(cli: T | None, env: T | None, file: T | None, default: T) -> T:
    for value in (cli, env, file):
        if value is not None:
            return value
    return default


def _parse_bool(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean: {value}")


def load_settings(
    config_file: Path,
    *,
    retries: int | None = None,
    debug: bool | None = None,
    label: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    environment = os.environ if environ is None else environ
    file_values = json.loads(config_file.read_text(encoding="utf-8"))
    env_retries = int(environment["APP_RETRIES"]) if "APP_RETRIES" in environment else None
    env_debug = _parse_bool(environment["APP_DEBUG"]) if "APP_DEBUG" in environment else None
    env_label = environment.get("APP_LABEL")
    return Settings(
        retries=_choose(retries, env_retries, file_values.get("retries"), 3),
        debug=_choose(debug, env_debug, file_values.get("debug"), False),
        label=_choose(label, env_label, file_values.get("label"), "default"),
    )
