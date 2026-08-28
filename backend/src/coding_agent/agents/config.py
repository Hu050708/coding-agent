"""Agent 单次运行使用的预算和重试配置。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """一次调用使用的硬预算和有界重试策略。"""

    max_model_calls: int = 16
    max_tool_calls: int = 40
    max_total_tokens: int = 200_000
    wall_time_seconds: float = 480.0
    api_timeout_seconds: float = 60.0
    max_transient_retries: int = 3
    retry_base_seconds: float = 0.25
    retry_jitter_seconds: float = 0.1
    max_task_chars: int = 100_000
    max_prior_messages: int = 48
    max_prior_chars: int = 80_000
    repeat_warning_threshold: int = 3
    max_repeat_fingerprints: int = 128

    def __post_init__(self) -> None:
        """校验所有预算类型、正负性和有限性，阻止无界配置进入状态机。"""

        # 第一步：统一识别排除布尔值的有限数值。
        def finite_number(value: Any) -> bool:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            try:
                return math.isfinite(value)
            except OverflowError:
                return False

        # 第二步：分别校验正整数预算、正数时限及非负重试参数。
        positive_ints = {
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_total_tokens": self.max_total_tokens,
            "max_task_chars": self.max_task_chars,
            "max_prior_messages": self.max_prior_messages,
            "max_prior_chars": self.max_prior_chars,
            "max_repeat_fingerprints": self.max_repeat_fingerprints,
        }
        for name, value in positive_ints.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.repeat_warning_threshold, bool)
            or not isinstance(self.repeat_warning_threshold, int)
            or self.repeat_warning_threshold < 2
        ):
            raise ValueError(
                "repeat_warning_threshold must be an integer greater than one"
            )
        positive_numbers = {
            "wall_time_seconds": self.wall_time_seconds,
            "api_timeout_seconds": self.api_timeout_seconds,
        }
        for name, value in positive_numbers.items():
            if not finite_number(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if (
            isinstance(self.max_transient_retries, bool)
            or not isinstance(self.max_transient_retries, int)
            or self.max_transient_retries < 0
        ):
            raise ValueError("max_transient_retries must be a non-negative integer")
        for name, value in {
            "retry_base_seconds": self.retry_base_seconds,
            "retry_jitter_seconds": self.retry_jitter_seconds,
        }.items():
            if not finite_number(value) or value < 0:
                raise ValueError(f"{name} must be non-negative and finite")


__all__ = ["AgentConfig"]
