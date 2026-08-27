"""Model-provider adapters."""

from coding_agent.providers.deepseek import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    DeepSeekAdapter,
    normalize_completion,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "DeepSeekAdapter",
    "normalize_completion",
]
