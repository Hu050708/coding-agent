"""Coding Agent 后端的集中配置。"""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from coding_agent.agents.providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
)


DEFAULT_ALLOWED_ROOT = Path(r"E:\code")
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
SettingsError = ValueError


def _default_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Coding Agent"
    return Path.home() / ".local" / "share" / "Coding Agent"


_ENV_FIELDS = {
    "DEEPSEEK_API_KEY": "api_key",
    "CODING_AGENT_DATABASE_URL": "database_url",
    "CODING_AGENT_ALLOWED_ROOT": "allowed_root",
    "CODING_AGENT_DATA_DIR": "data_dir",
    "CODING_AGENT_MODEL": "model",
    "CODING_AGENT_BASE_URL": "base_url",
    "CODING_AGENT_MAX_TOKENS": "max_tokens",
    "CODING_AGENT_MAX_ACTIVE_RUNS": "max_active_runs",
    "CODING_AGENT_MAX_RETAINED_RUNS": "max_retained_runs",
    "CODING_AGENT_EVENT_BUFFER_SIZE": "event_buffer_size",
    "CODING_AGENT_APPROVAL_TIMEOUT_SECONDS": "approval_timeout_seconds",
    "CODING_AGENT_MAX_MODEL_CALLS": "max_model_calls",
    "CODING_AGENT_MAX_TOOL_CALLS": "max_tool_calls",
    "CODING_AGENT_MAX_TOTAL_TOKENS": "max_total_tokens",
    "CODING_AGENT_WALL_TIME_SECONDS": "wall_time_seconds",
    "CODING_AGENT_API_TIMEOUT_SECONDS": "api_timeout_seconds",
    "CODING_AGENT_MAX_TRANSIENT_RETRIES": "max_transient_retries",
    "CODING_AGENT_TRACE_ENABLED": "trace_enabled",
    "CODING_AGENT_WEB_PORT": "port",
}


class AppSettings(BaseSettings):
    """由后端进程共享、可在测试中显式注入的配置。"""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    api_key: str = Field(default="", repr=False)
    database_url: str = Field(default="", repr=False)
    allowed_root: Path = DEFAULT_ALLOWED_ROOT
    data_dir: Path = Field(default_factory=_default_data_dir)
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1)
    max_active_runs: int = Field(default=4, ge=1)
    max_retained_runs: int = Field(default=50, ge=1)
    event_buffer_size: int = Field(default=256, ge=1)
    approval_timeout_seconds: float = Field(default=480.0, gt=0)
    max_model_calls: int = Field(default=16, ge=1)
    max_tool_calls: int = Field(default=40, ge=1)
    max_total_tokens: int = Field(default=200_000, ge=1)
    wall_time_seconds: float = Field(default=480.0, gt=0)
    api_timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    max_transient_retries: int = Field(default=3, ge=0)
    trace_enabled: bool = True
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65_535)

    @field_validator("api_key", "database_url", "model", "base_url")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("model")
    @classmethod
    def _model_required(cls, value: str) -> str:
        if not value:
            raise ValueError("The model must be non-empty text.")
        return value

    @field_validator("allowed_root")
    @classmethod
    def _resolve_allowed_root(cls, value: Path) -> Path:
        root = value.expanduser()
        if not root.is_absolute():
            raise ValueError("CODING_AGENT_ALLOWED_ROOT must be an absolute path.")
        try:
            root = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("CODING_AGENT_ALLOWED_ROOT must be an existing directory.") from exc
        if not root.is_dir():
            raise ValueError("CODING_AGENT_ALLOWED_ROOT must be a directory.")
        return root

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        path = value.expanduser()
        if not path.is_absolute():
            raise ValueError("CODING_AGENT_DATA_DIR must be an absolute path.")
        return path.resolve(strict=False)

    @field_validator("database_url")
    @classmethod
    def _local_postgres_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "postgresql+psycopg"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or not parsed.username
            or parsed.password is None
            or not parsed.path.strip("/")
        ):
            raise ValueError(
                "CODING_AGENT_DATABASE_URL must be a loopback-only "
                "postgresql+psycopg URL with credentials and a database name."
            )
        return value

    @model_validator(mode="after")
    def _cross_field_rules(self) -> "AppSettings":
        if self.max_retained_runs < self.max_active_runs:
            raise ValueError("max_retained_runs must be at least max_active_runs.")
        try:
            common = os.path.commonpath((self.allowed_root, self.data_dir))
        except ValueError:
            common = ""
        if os.path.normcase(common) == os.path.normcase(os.fspath(self.allowed_root)):
            raise ValueError("CODING_AGENT_DATA_DIR must be outside CODING_AGENT_ALLOWED_ROOT.")
        return self

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        env_file: str | os.PathLike[str] | None = DEFAULT_ENV_FILE,
    ) -> "AppSettings":
        """按“进程环境优先、项目 .env 兜底”的顺序加载配置。"""

        source: dict[str, str] = {}
        if env_file is not None and Path(env_file).is_file():
            source.update(
                {
                    key: value
                    for key, value in dotenv_values(env_file, encoding="utf-8-sig").items()
                    if value is not None
                }
            )
        source.update(os.environ if environ is None else environ)
        values = {
            field_name: source[env_name]
            for env_name, field_name in _ENV_FIELDS.items()
            if env_name in source
        }
        return cls.model_validate(values)


__all__ = ["AppSettings", "DEFAULT_ALLOWED_ROOT", "DEFAULT_ENV_FILE", "SettingsError"]
