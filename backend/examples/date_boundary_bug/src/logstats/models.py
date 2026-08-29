"""日志统计示例的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LogRecord:
    """一条规范化后的日志记录。"""

    # 日志事件发生的无时区时间戳。
    timestamp: datetime
    # 日志级别文本。
    level: str

    @classmethod
    def from_values(cls, *, timestamp: str, level: str) -> "LogRecord":
        """根据 JSON 输入中的原始值构建日志记录。

        :param timestamp: ISO 8601 格式的时间戳文本。
        :param level: 非空日志级别文本。
        :return: 类型化的不可变日志记录。
        :raises ValueError: 时间戳无法按 ISO 8601 解析。
        """

        return cls(timestamp=datetime.fromisoformat(timestamp), level=level)
