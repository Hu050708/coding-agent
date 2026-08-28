"""协调工作区记忆持久化变更的应用服务。"""

from __future__ import annotations

from typing import Any

from coding_agent.repository import (
    MemorySource,
    PersistenceConflictError,
    PersistenceNotFoundError,
    PersistenceService,
    RunStatus,
)

from .errors import ApplicationError
from .presenters import memory_view


class WorkspaceMemoryService:
    """实现需要手动确认的工作区级长期记忆用例。"""

    def __init__(self, persistence: PersistenceService) -> None:
        self.persistence = persistence

    def list(self, workspace_id: str) -> list[dict[str, Any]]:
        try:
            items = self.persistence.list_memories(workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc
        return [memory_view(item) for item in items]

    def create(
        self,
        workspace_id: str,
        *,
        kind: str,
        content: str,
        pinned: bool,
        source_run_id: str | None,
    ) -> dict[str, Any]:
        """创建手工或运行结果记忆，并校验工作区可变性和来源资格。"""

        # 第一步：排除活动运行，避免运行快照与记忆变更发生竞态。
        self._require_mutable(workspace_id)
        source = MemorySource.MANUAL
        # 第二步：运行结果记忆只能引用同工作区内已完成的运行。
        if source_run_id is not None:
            try:
                run = self.persistence.get_run(source_run_id)
            except PersistenceNotFoundError as exc:
                raise ApplicationError(404, "source_run_not_found", "Source run was not found.") from exc
            if str(run.workspace_id) != str(workspace_id):
                raise ApplicationError(
                    409,
                    "source_run_workspace_mismatch",
                    "The source run belongs to a different workspace.",
                )
            if run.status != RunStatus.COMPLETED.value:
                raise ApplicationError(
                    409,
                    "source_run_ineligible",
                    "Only a completed run can be saved as workspace memory.",
                )
            source = MemorySource.RUN_RESULT
        # 第三步：写入持久化层，并将底层不存在或去重冲突转换为应用错误。
        try:
            record = self.persistence.create_memory(
                workspace_id=workspace_id,
                kind=kind,
                content=content,
                source=source,
                source_run_id=source_run_id,
                pinned=pinned,
            )
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc
        except PersistenceConflictError as exc:
            raise ApplicationError(
                409, "memory_already_exists", "The same workspace memory already exists."
            ) from exc
        return memory_view(record)

    def update(
        self,
        workspace_id: str,
        memory_id: str,
        *,
        kind: str | None,
        content: str | None,
        pinned: bool | None,
        enabled: bool | None,
    ) -> dict[str, Any]:
        self._require_mutable(workspace_id)
        try:
            record = self.persistence.update_memory(
                workspace_id,
                memory_id,
                kind=kind,
                content=content,
                pinned=pinned,
                enabled=enabled,
            )
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "memory_not_found", "Memory entry was not found.") from exc
        except PersistenceConflictError as exc:
            raise ApplicationError(
                409, "memory_already_exists", "The same workspace memory already exists."
            ) from exc
        return memory_view(record)

    def delete(self, workspace_id: str, memory_id: str) -> None:
        self._require_mutable(workspace_id)
        try:
            self.persistence.delete_memory(workspace_id, memory_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "memory_not_found", "Memory entry was not found.") from exc

    def purge(self, workspace_id: str) -> int:
        self._require_mutable(workspace_id)
        try:
            return self.persistence.purge_memories(workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc

    def _require_mutable(self, workspace_id: str) -> None:
        try:
            self.persistence.get_workspace(workspace_id)
            active = self.persistence.active_run_for_workspace(workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc
        if active is not None:
            raise ApplicationError(
                409,
                "memory_workspace_busy",
                "Workspace memory cannot change while an agent run is active.",
            )


__all__ = ["WorkspaceMemoryService"]
