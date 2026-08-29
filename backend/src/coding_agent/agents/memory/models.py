"""工作区范围项目记忆使用的不可变领域值。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal


class MemoryKind(str, Enum):
    """记忆内容的业务分类。"""

    PREFERENCE = "preference"
    FACT = "fact"
    DECISION = "decision"
    NOTE = "note"


class MemorySource(str, Enum):
    """记忆条目的产生来源。"""

    MANUAL = "manual"
    RUN_RESULT = "run_result"


MemoryStatus = Literal["pending", "loaded", "empty", "disabled", "unavailable"]


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """提供给应用层和用户界面的工作区记忆条目。"""

    # 记忆条目的稳定唯一标识。
    id: str
    # 用户可见且已经规范化的工作区绝对路径。
    workspace: str
    # 内容的业务分类，例如偏好、事实或决策。
    kind: MemoryKind
    # 实际注入上下文的记忆文本。
    content: str
    # 条目是人工创建还是由一次运行结果生成。
    source: MemorySource
    # 自动生成条目所关联的运行 ID；人工条目为 None。
    source_run_id: str | None
    # 是否优先装载到有限的上下文预算中。
    pinned: bool
    # 是否允许该条目参与后续上下文构建。
    enabled: bool
    # 首次创建时间。
    created_at: datetime
    # 最近一次更新时间。
    updated_at: datetime

    def as_dict(self) -> dict[str, object]:
        """把条目转换为可序列化的字段字典。

        :return: 保留枚举值和时间对象语义的字段字典。
        """

        return {
            "id": self.id,
            "workspace": self.workspace,
            "kind": self.kind.value,
            "content": self.content,
            "source": self.source.value,
            "source_run_id": self.source_run_id,
            "pinned": self.pinned,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class StoredMemory:
    """不包含用户可见规范工作区路径的仓储记录。"""

    # 记忆条目的稳定唯一标识。
    id: str
    # 由规范工作区路径计算出的不可逆仓储键。
    workspace_key: str
    # 内容的业务分类。
    kind: MemoryKind
    # 持久化的记忆正文。
    content: str
    # 条目的产生来源。
    source: MemorySource
    # 自动生成条目所关联的运行 ID。
    source_run_id: str | None
    # 是否在快照排序时优先选择。
    pinned: bool
    # 是否允许装载到 Agent 上下文。
    enabled: bool
    # 规范化正文的哈希，用于工作区内去重。
    content_hash: str
    # 首次创建时间。
    created_at: datetime
    # 最近一次更新时间。
    updated_at: datetime


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


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """在单次 Agent 运行开始前冻结的有限记忆集合。"""

    # 快照是否成功选中了至少一条记忆。
    status: Literal["loaded", "empty"]
    # 按优先级排序且受数量、字符预算约束的条目。
    entries: tuple[MemoryEntry, ...] = ()

    @property
    def summary(self) -> MemorySummary:
        """生成不包含正文的快照摘要。

        :return: 可安全附加到运行元数据中的记忆摘要。
        """

        return MemorySummary(
            status=self.status,
            loaded_count=len(self.entries),
            loaded_ids=tuple(entry.id for entry in self.entries),
        )


__all__ = [
    "MemoryEntry",
    "MemoryKind",
    "MemorySnapshot",
    "MemorySource",
    "MemoryStatus",
    "MemorySummary",
    "StoredMemory",
]
