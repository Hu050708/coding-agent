"""负责构建并管理应用层服务的生命周期。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from coding_agent.repository import PersistenceService
from coding_agent.agents.runtime.run_manager import RunManager
from coding_agent.agents.security import WorkspacePolicy

from .catalog_service import CatalogService
from .evaluation_service import EvaluationReportService
from .memory_service import WorkspaceMemoryService
from .run_service import ConversationRunService


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """应用层共享业务服务的不可变容器。"""

    # 工作区、会话和消息目录服务。
    catalog: CatalogService
    # Agent 运行生命周期服务。
    runs: ConversationRunService
    # 工作区长期记忆服务。
    memories: WorkspaceMemoryService
    # 本地 benchmark 结果只读服务。
    evaluations: EvaluationReportService

    @classmethod
    def build(
        cls,
        *,
        persistence: PersistenceService,
        manager: RunManager,
        workspace_policy: WorkspacePolicy,
        benchmark_runs_dir: Path,
    ) -> "ApplicationServices":
        """使用共享对象创建全部业务服务。

        :param persistence: 数据库操作对象。
        :param manager: 内存 Agent 运行协调器。
        :param workspace_policy: 文件系统工作区边界策略。
        :return: 可挂载到 FastAPI 应用状态的服务容器。
        """

        return cls(
            catalog=CatalogService(persistence, workspace_policy),
            runs=ConversationRunService(persistence, manager),
            memories=WorkspaceMemoryService(persistence),
            evaluations=EvaluationReportService(benchmark_runs_dir),
        )


__all__ = ["ApplicationServices"]
