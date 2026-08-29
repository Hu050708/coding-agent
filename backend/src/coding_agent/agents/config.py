"""Agent 单次运行使用的预算和重试配置。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """一次调用使用的硬预算、上下文容量和有界重试策略。"""

    # 单次 Agent 运行最多允许向模型发起的请求次数。
    max_model_calls: int = 50
    # 单次 Agent 运行最多允许执行的工具调用总数。
    max_tool_calls: int = 100
    # 单次 Agent 运行允许消耗的输入与输出 Token 总数上限。
    max_total_tokens: int = 1000_000
    # 单次 Agent 运行从开始到结束允许占用的最长时间，单位为秒。
    wall_time_seconds: float = 600.0
    # 每次模型 API 请求等待响应的最长时间，单位为秒。
    api_timeout_seconds: float = 60.0
    # 一轮模型请求发生可重试瞬时错误时，允许追加的最大重试次数。
    max_transient_retries: int = 3
    # 瞬时错误首次重试前的基础等待时间，单位为秒；后续重试按指数增加。
    retry_base_seconds: float = 0.25
    # 重试等待时间中加入的最大随机抖动，单位为秒，用于避免请求同时重发。
    retry_jitter_seconds: float = 0.1
    # 当前用户任务允许包含的最大字符数，超过后拒绝运行。
    max_task_chars: int = 500_000
    # Agent 接受的历史会话消息最大条数，避免上下文无限增长。
    max_prior_messages: int = 48
    # Agent 接受的历史会话消息最大字符总数。
    max_prior_chars: int = 100_000
    # 单条历史消息允许占用的最大字符数，避免一条消息挤满上下文。
    max_message_chars: int = 24_000
    # 最多向模型提供的工作区记忆条数。
    max_memory_entries: int = 32
    # 所有工作区记忆允许占用的最大字符总数。
    max_memory_chars: int = 32_000
    # 单条工作区记忆允许占用的最大字符数。
    max_memory_item_chars: int = 4_000
    # 同一工具调用及结果累计重复多少次后，向模型附加避免重复的警告。
    repeat_warning_threshold: int = 3
    # 重复调用检测器最多保留的工具交换指纹数量，防止内存无界增长。
    max_repeat_fingerprints: int = 256

    def __post_init__(self) -> None:
        """校验所有预算类型、正负性和有限性，阻止无界配置进入状态机。"""

        # 第一步：统一识别排除布尔值的有限数值。
        def finite_number(value: Any) -> bool:
            """判断输入是否为非布尔类型的有限整数或浮点数。

            :param value: 待校验的任意配置值。
            :return: 值属于有限实数时返回 ``True``。
            """

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
            "max_message_chars": self.max_message_chars,
            "max_memory_entries": self.max_memory_entries,
            "max_memory_chars": self.max_memory_chars,
            "max_memory_item_chars": self.max_memory_item_chars,
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
