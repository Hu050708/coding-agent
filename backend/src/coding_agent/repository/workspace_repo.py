"""事务级实体仓储。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from coding_agent.models import (
    Approval,
    ApprovalStatus,
    Conversation,
    MemoryEntry,
    MemoryKind,
    MemorySource,
    Message,
    MessageRole,
    PermissionMode,
    Run,
    RunEvent,
    RunMemory,
    RunStatus,
    Workspace,
)

from .base import (
    MAX_MEMORY_CHARS,
    MAX_MEMORY_CONTENT_CHARS,
    MAX_MEMORY_ENTRIES,
    UUIDLike,
    PersistenceConflictError,
    PersistenceNotFoundError,
    _required_text,
    _validate_run_transition,
    as_uuid,
    utc_now,
)
from .safe_events import safe_approval_data, sanitize_run_event
class WorkspaceRepository:
    """封装工作区表的创建、查询、锁定和归档操作。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, *, canonical_path: str, path_key: str, display_name: str
    ) -> Workspace:
        item = Workspace(
            canonical_path=_required_text(canonical_path, label="canonical_path"),
            path_key=_required_text(path_key, label="path_key", limit=2048),
            display_name=_required_text(display_name, label="display_name", limit=255),
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get(
        self,
        workspace_id: UUIDLike,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Workspace | None:
        statement = select(Workspace).where(Workspace.id == as_uuid(workspace_id))
        if not include_deleted:
            statement = statement.where(Workspace.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def require(self, workspace_id: UUIDLike, *, for_update: bool = False) -> Workspace:
        item = self.get(workspace_id, for_update=for_update)
        if item is None:
            raise PersistenceNotFoundError("workspace was not found")
        return item

    def get_by_path_key(self, path_key: str) -> Workspace | None:
        return self.session.scalar(
            select(Workspace).where(
                Workspace.path_key == _required_text(path_key, label="path_key", limit=2048),
                Workspace.deleted_at.is_(None),
            )
        )

    def list(self, *, include_archived: bool = False) -> list[Workspace]:
        statement = select(Workspace).where(Workspace.deleted_at.is_(None))
        if not include_archived:
            statement = statement.where(Workspace.archived_at.is_(None))
        statement = statement.order_by(Workspace.updated_at.desc(), Workspace.display_name)
        return list(self.session.scalars(statement))

    def archive(self, workspace_id: UUIDLike, *, archived: bool = True) -> Workspace:
        item = self.require(workspace_id, for_update=True)
        item.archived_at = utc_now() if archived else None
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def soft_delete(self, workspace_id: UUIDLike) -> Workspace:
        item = self.require(workspace_id, for_update=True)
        now = utc_now()
        item.deleted_at = now
        item.archived_at = item.archived_at or now
        item.updated_at = now
        self.session.flush()
        return item


