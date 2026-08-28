"""工作区范围项目记忆使用的不可变领域值。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal


class MemoryKind(str, Enum):
    PREFERENCE = "preference"
    FACT = "fact"
    DECISION = "decision"
    NOTE = "note"


class MemorySource(str, Enum):
    MANUAL = "manual"
    RUN_RESULT = "run_result"


MemoryStatus = Literal["pending", "loaded", "empty", "disabled", "unavailable"]


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: str
    workspace: str
    kind: MemoryKind
    content: str
    source: MemorySource
    source_run_id: str | None
    pinned: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, object]:
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

    id: str
    workspace_key: str
    kind: MemoryKind
    content: str
    source: MemorySource
    source_run_id: str | None
    pinned: bool
    enabled: bool
    content_hash: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemorySummary:
    status: MemoryStatus
    loaded_count: int = 0
    loaded_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "loaded_count": self.loaded_count,
            "loaded_ids": list(self.loaded_ids),
        }


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    status: Literal["loaded", "empty"]
    entries: tuple[MemoryEntry, ...] = ()

    @property
    def summary(self) -> MemorySummary:
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
