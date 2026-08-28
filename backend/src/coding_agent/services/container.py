"""负责构建并管理应用层服务的生命周期。"""

from __future__ import annotations

from dataclasses import dataclass

from coding_agent.repository import PersistenceService
from coding_agent.agents.runtime.run_manager import RunManager
from coding_agent.agents.security import WorkspacePolicy

from .catalog_service import CatalogService
from .memory_service import WorkspaceMemoryService
from .run_service import ConversationRunService


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    catalog: CatalogService
    runs: ConversationRunService
    memories: WorkspaceMemoryService

    @classmethod
    def build(
        cls,
        *,
        persistence: PersistenceService,
        manager: RunManager,
        workspace_policy: WorkspacePolicy,
    ) -> "ApplicationServices":
        return cls(
            catalog=CatalogService(persistence, workspace_policy),
            runs=ConversationRunService(persistence, manager),
            memories=WorkspaceMemoryService(persistence),
        )


__all__ = ["ApplicationServices"]
