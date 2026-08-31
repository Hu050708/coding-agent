"""Agent 运行过程使用的记忆加载摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MemoryStatus = Literal["pending", "loaded", "empty", "disabled", "unavailable"]


@dataclass(frozen=True, slots=True)
class MemorySummary:
    """一次运行装载项目记忆的摘要。"""

    # 当前装载状态，例如待处理、已装载或不可用。
    status: MemoryStatus
    # 实际装载的条目数量。
    loaded_count: int = 0
    # 实际装载的条目 ID，便于审计和追踪。
    loaded_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """把摘要转换为适合 API 返回的字典。

        :return: 包含状态、数量和条目 ID 列表的字典。
        """

        return {
            "status": self.status,
            "loaded_count": self.loaded_count,
            "loaded_ids": list(self.loaded_ids),
        }
__all__ = ["MemoryStatus", "MemorySummary"]
