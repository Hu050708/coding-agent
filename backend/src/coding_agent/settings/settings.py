"""Coding Agent 后端配置。"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from coding_agent.agents.config import AgentConfig
from coding_agent.agents.providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
)


_AGENT_DEFAULTS = AgentConfig()


def default_data_dir() -> Path:
    """计算当前操作系统上的默认应用数据目录。

    :return: Windows 优先使用 LOCALAPPDATA，否则使用用户目录下的隐藏目录。
    """

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

    # DeepSeek API 密钥；从环境读取且不会出现在对象 repr 中。
    api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY", repr=False)
    # PostgreSQL 的 SQLAlchemy 连接 URL，同样禁止在 repr 中显示。
    database_url: str = Field(default="", repr=False)
    # 用户可选择为工作区的最高层目录边界。
    allowed_root: Path = Path(r"E:\code")
    # 日志、追踪等本地运行数据的保存目录。
    data_dir: Path = Field(default_factory=default_data_dir)
    # 调用模型服务时使用的模型名称。
    model: str = DEFAULT_MODEL
    # OpenAI 兼容模型接口的基础 URL。
    base_url: str = DEFAULT_BASE_URL
    # 单次模型响应允许生成的最大 token 数。
    max_tokens: int = DEFAULT_MAX_TOKENS
    # Web 进程允许同时执行的最大 Agent 运行数。
    max_active_runs: int = 4
    # 内存管理器最多保留的已结束运行数。
    max_retained_runs: int = 50
    # 每次运行在内存中保留的最近事件数量。
    event_buffer_size: int = 256
    # 等待用户审批命令的最长秒数。
    approval_timeout_seconds: float = 480.0
    # 单次 Agent 运行允许调用模型的次数。
    max_model_calls: int = _AGENT_DEFAULTS.max_model_calls
    # 单次 Agent 运行允许执行工具的次数。
    max_tool_calls: int = _AGENT_DEFAULTS.max_tool_calls
    # 单次 Agent 运行累计使用的最大 token 数。
    max_total_tokens: int = _AGENT_DEFAULTS.max_total_tokens
    # 单次 Agent 运行的总墙钟时间上限（秒）。
    wall_time_seconds: float = _AGENT_DEFAULTS.wall_time_seconds
    # 单次模型 API 请求的超时时间（秒）。
    api_timeout_seconds: float = _AGENT_DEFAULTS.api_timeout_seconds
    # 瞬时模型接口错误允许自动重试的最大次数。
    max_transient_retries: int = _AGENT_DEFAULTS.max_transient_retries
    # 是否把运行追踪事件写入本地文件。
    trace_enabled: bool = True
    # Web 服务监听地址；默认仅允许本机访问。
    host: str = "127.0.0.1"
    # Web 服务监听端口。
    port: int = Field(default=8000, validation_alias="CODING_AGENT_WEB_PORT")

    @property
    def api_key_configured(self) -> bool:
        """判断是否配置了非空模型 API 密钥。

        :return: 密钥非空时为 True。
        """

        return bool(self.api_key)

    @property
    def database_configured(self) -> bool:
        """判断是否配置了非空数据库连接 URL。

        :return: 数据库 URL 非空时为 True。
        """

        return bool(self.database_url)


__all__ = ["AppSettings"]
