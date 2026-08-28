"""日志统计示例的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LogRecord:
    """一条规范化后的日志记录。"""

    timestamp: datetime
    level: str

    @classmethod
    def from_values(cls, *, timestamp: str, level: str) -> "LogRecord":
        """根据 JSON 输入中的原始值构建日志记录。"""

        return cls(timestamp=datetime.fromisoformat(timestamp), level=level)
