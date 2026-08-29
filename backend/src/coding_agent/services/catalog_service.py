"""实现工作区与会话目录管理的应用服务。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from coding_agent.repository import (
    PersistenceConflictError,
    PersistenceNotFoundError,
    PersistenceService,
)
from coding_agent.agents.security import WorkspacePolicy, WorkspacePolicyError

from .errors import ApplicationError
from .filesystem_browser import DirectoryBrowser
from .presenters import (
    conversation_view,
    dated_conversation_title,
    message_view,
    workspace_view,
)


class CatalogService:
    """实现工作区、会话和可见消息用例。"""

    def __init__(
        self,
        persistence: PersistenceService,
        workspace_policy: WorkspacePolicy,
    ) -> None:
        """初始化目录服务及受限文件夹浏览器。

        :param persistence: 负责工作区、会话和消息事务的持久化门面。
        :param workspace_policy: 负责工作区路径边界校验的安全策略。
        """

        # 两项共享依赖分别负责数据库事务与文件系统信任边界。
        self.persistence = persistence
        self.workspace_policy = workspace_policy
        self.browser = DirectoryBrowser(workspace_policy)

    def browse_directories(self, path: str | None = None) -> dict[str, object]:
        """浏览允许根目录内的直接子目录。

        :param path: 待浏览目录；None 表示从允许根目录开始。
        :return: 当前目录、父目录和可访问子目录的安全视图。
        """

        return self.browser.browse(path)

    def list_workspaces(self) -> list[dict[str, Any]]:
        """列出活动工作区的公开视图。

        :return: 不暴露允许根目录完整信息的工作区字典列表。
        """

        return [
            workspace_view(item, allowed_root=self.workspace_policy.allowed_root)
            for item in self.persistence.list_workspaces()
        ]

    def create_workspace(
        self, *, path: str, display_name: str | None = None
    ) -> dict[str, Any]:
        """校验本地目录后，将其登记为 Agent 可操作的工作区。

        :param path: 待登记的本地目录路径。
        :param display_name: 可选显示名称；省略时使用目录名。
        :return: 新工作区的公开 API 视图。
        :raises ApplicationError: 路径无效、越界或已经登记。
        """

        # 第一步：由工作区策略解析真实路径并确认目录位于允许根目录内。
        try:
            canonical = self.workspace_policy.validate(path)
        except WorkspacePolicyError as exc:
            raise ApplicationError(400, exc.code, exc.message) from exc
        name = display_name.strip() if display_name is not None else canonical.name
        if not name:
            name = os.fspath(canonical)
        # 第二步：以规范路径键去重登记，并将持久化冲突转换为 API 可读错误。
        try:
            record = self.persistence.create_workspace(
                canonical_path=os.fspath(canonical),
                path_key=_path_key(canonical),
                display_name=name,
            )
        except PersistenceConflictError as exc:
            raise ApplicationError(
                409, "workspace_already_registered", "This workspace is already registered."
            ) from exc
        return workspace_view(record, allowed_root=self.workspace_policy.allowed_root)

    def delete_workspace(self, workspace_id: str) -> None:
        """删除没有活动运行的工作区登记。

        :param workspace_id: 目标工作区 ID 文本。
        :raises ApplicationError: 工作区不存在或仍有活动运行。
        """

        try:
            self.persistence.delete_workspace(workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc
        except PersistenceConflictError as exc:
            raise ApplicationError(
                409, "workspace_busy", "The workspace has an active run."
            ) from exc

    def list_conversations(self, workspace_id: str) -> list[dict[str, Any]]:
        """列出工作区会话并标注其活动运行。

        :param workspace_id: 工作区 ID 文本。
        :return: 会话公开视图列表。
        :raises ApplicationError: 工作区不存在。
        """

        try:
            self.persistence.get_workspace(workspace_id)
            active = self.persistence.active_run_for_workspace(workspace_id)
            items = self.persistence.list_conversations(workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc
        return [conversation_view(item, active_run=active) for item in items]

    def create_conversation(
        self,
        *,
        workspace_id: str,
        title: str | None,
        default_permission_mode: str,
        use_memory: bool,
    ) -> dict[str, Any]:
        """在指定工作区下创建带默认运行设置的会话。

        :param workspace_id: 所属工作区 ID。
        :param title: 可选标题；省略时使用带创建日期的默认标题。
        :param default_permission_mode: 新运行的默认权限模式。
        :param use_memory: 新运行默认是否使用项目记忆。
        :return: 新会话公开视图。
        :raises ApplicationError: 工作区不存在、归档或不可用。
        """

        # 第一步：把前端设置原样交给事务服务，并为缺省标题提供用户可见名称。
        try:
            record = self.persistence.create_conversation(
                workspace_id=workspace_id,
                title=title or dated_conversation_title(),
                default_permission_mode=default_permission_mode,
                use_memory=use_memory,
            )
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc
        except PersistenceConflictError as exc:
            raise ApplicationError(
                409, "workspace_unavailable", "The workspace is archived or unavailable."
            ) from exc
        # 第二步：通过统一 presenter 输出 API 结构，避免路由直接依赖 ORM 模型。
        return conversation_view(record)

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        """读取会话及其可能的活动运行。

        :param conversation_id: 会话 ID 文本。
        :return: 会话公开视图。
        :raises ApplicationError: 会话不存在。
        """

        try:
            record = self.persistence.get_conversation(conversation_id)
            active = self.persistence.active_run_for_workspace(record.workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(
                404, "conversation_not_found", "Conversation was not found."
            ) from exc
        return conversation_view(record, active_run=active)

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None,
        default_permission_mode: str | None,
        use_memory: bool | None,
    ) -> dict[str, Any]:
        """部分更新会话设置并附带当前工作区运行状态。

        :param conversation_id: 目标会话 ID。
        :param title: 新标题；None 表示不修改。
        :param default_permission_mode: 新默认权限；None 表示不修改。
        :param use_memory: 新默认记忆开关；None 表示不修改。
        :return: 更新后的会话公开视图。
        :raises ApplicationError: 会话不存在。
        """

        # 第一步：先读取会话以确定所属工作区，再执行限定工作区的更新。
        try:
            current = self.persistence.get_conversation(conversation_id)
            record = self.persistence.update_conversation(
                current.workspace_id,
                conversation_id,
                title=title,
                default_permission_mode=default_permission_mode,
                use_memory=use_memory,
            )
            active = self.persistence.active_run_for_workspace(record.workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(
                404, "conversation_not_found", "Conversation was not found."
            ) from exc
        # 第二步：将活动运行一并投影到响应，供前端恢复正在进行的任务。
        return conversation_view(record, active_run=active)

    def delete_conversation(self, conversation_id: str) -> None:
        """删除没有活动运行的会话。

        :param conversation_id: 目标会话 ID。
        :raises ApplicationError: 会话不存在或仍有活动运行。
        """

        try:
            current = self.persistence.get_conversation(conversation_id)
            self.persistence.delete_conversation(current.workspace_id, conversation_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(
                404, "conversation_not_found", "Conversation was not found."
            ) from exc
        except PersistenceConflictError as exc:
            raise ApplicationError(
                409, "conversation_busy", "The conversation has an active run."
            ) from exc

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """列出会话中的全部可见消息。

        :param conversation_id: 会话 ID。
        :return: 按序号排列的消息公开视图。
        :raises ApplicationError: 会话不存在。
        """

        try:
            records = self.persistence.list_messages(conversation_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(
                404, "conversation_not_found", "Conversation was not found."
            ) from exc
        return [message_view(item) for item in records]


def _path_key(path: Path) -> str:
    """生成适合当前操作系统进行唯一比较的绝对路径键。

    :param path: 已解析的工作区路径。
    :return: 经过绝对化和大小写规范化的路径文本。
    """

    return os.path.normcase(os.path.abspath(os.fspath(path)))


__all__ = ["CatalogService"]
