"""将持久化记录转换为稳定的 API 输出字典。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from coding_agent.repository import (
    ConversationRecord,
    MemoryEntryRecord,
    MessageRecord,
    RunEventRecord,
    RunRecord,
    WorkspaceRecord,
)


def workspace_view(record: WorkspaceRecord, *, allowed_root: Path) -> dict[str, Any]:
    """将工作区记录转换为不暴露完整允许根目录的 API 视图。"""

    try:
        relative = Path(record.canonical_path).relative_to(allowed_root)
        path_hint = os.fspath(relative) if relative.parts else "."
    except ValueError:
        path_hint = Path(record.canonical_path).name
    return {
        "id": record.id,
        "display_name": record.display_name,
        "path_hint": path_hint,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "archived_at": record.archived_at,
    }


def conversation_view(
    record: ConversationRecord,
    *,
    active_run: RunRecord | None = None,
) -> dict[str, Any]:
    """生成会话视图，并在活动运行属于该会话时附加运行编号。"""

    return {
        "id": record.id,
        "workspace_id": record.workspace_id,
        "title": record.title,
        "default_permission_mode": record.default_permission_mode,
        "use_memory": record.use_memory,
        "active_run_id": (
            active_run.id
            if active_run is not None and active_run.conversation_id == record.id
            else None
        ),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def message_view(record: MessageRecord) -> dict[str, Any]:
    """将消息记录转换为稳定的公开字段。"""

    return {
        "id": record.id,
        "conversation_id": record.conversation_id,
        "run_id": record.run_id,
        "seq": record.seq,
        "role": record.role,
        "content": record.content,
        "created_at": record.created_at,
    }


def event_view(record: RunEventRecord) -> dict[str, Any]:
    """将可重放运行事件转换为 SSE/API 共用视图。"""

    return {
        "seq": record.seq,
        "event": record.event,
        "timestamp": record.occurred_at,
        "data": dict(record.data),
    }


def memory_view(record: MemoryEntryRecord) -> dict[str, Any]:
    """将长期记忆记录转换为前端可编辑视图。"""

    return {
        "id": record.id,
        "workspace_id": record.workspace_id,
        "kind": record.kind,
        "content": record.content,
        "source": record.source,
        "source_run_id": record.source_run_id,
        "pinned": record.pinned,
        "enabled": record.enabled,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


__all__ = [
    "conversation_view",
    "event_view",
    "memory_view",
    "message_view",
    "workspace_view",
]
