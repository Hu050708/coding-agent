"""Coding Agent 后端配置。"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from coding_agent.agents.providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
)


def default_data_dir() -> Path:
    base = os.getenv("LOCALAPPDATA")
    return Path(base) / "Coding Agent" if base else Path.home() / ".coding-agent"


class AppSettings(BaseSettings):
    """从项目 `.env` 和进程环境读取运行参数。"""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8-sig",
        env_prefix="CODING_AGENT_",
        populate_by_name=True,
        extra="ignore",
        frozen=True,
    )

    api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY", repr=False)
    database_url: str = Field(default="", repr=False)
    allowed_root: Path = Path(r"E:\code")
    data_dir: Path = Field(default_factory=default_data_dir)
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_active_runs: int = 4
    max_retained_runs: int = 50
    event_buffer_size: int = 256
    approval_timeout_seconds: float = 480.0
    max_model_calls: int = 16
    max_tool_calls: int = 40
    max_total_tokens: int = 200_000
    wall_time_seconds: float = 480.0
    api_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_transient_retries: int = 3
    trace_enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8000, validation_alias="CODING_AGENT_WEB_PORT")

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)


__all__ = ["AppSettings"]
