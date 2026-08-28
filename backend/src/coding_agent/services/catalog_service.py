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
from .presenters import conversation_view, message_view, workspace_view


class CatalogService:
    """实现工作区、会话和可见消息用例。"""

    def __init__(
        self,
        persistence: PersistenceService,
        workspace_policy: WorkspacePolicy,
    ) -> None:
        self.persistence = persistence
        self.workspace_policy = workspace_policy
        self.browser = DirectoryBrowser(workspace_policy)

    def browse_directories(self, path: str | None = None) -> dict[str, object]:
        return self.browser.browse(path)

    def list_workspaces(self) -> list[dict[str, Any]]:
        return [
            workspace_view(item, allowed_root=self.workspace_policy.allowed_root)
            for item in self.persistence.list_workspaces()
        ]

    def create_workspace(
        self, *, path: str, display_name: str | None = None
    ) -> dict[str, Any]:
        try:
            canonical = self.workspace_policy.validate(path)
        except WorkspacePolicyError as exc:
            raise ApplicationError(400, exc.code, exc.message) from exc
        name = display_name.strip() if display_name is not None else canonical.name
        if not name:
            name = os.fspath(canonical)
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
        try:
            self.persistence.delete_workspace(workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc
        except PersistenceConflictError as exc:
            raise ApplicationError(
                409, "workspace_busy", "The workspace has an active run."
            ) from exc

    def list_conversations(self, workspace_id: str) -> list[dict[str, Any]]:
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
        try:
            record = self.persistence.create_conversation(
                workspace_id=workspace_id,
                title=title or "新会话",
                default_permission_mode=default_permission_mode,
                use_memory=use_memory,
            )
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "workspace_not_found", "Workspace was not found.") from exc
        except PersistenceConflictError as exc:
            raise ApplicationError(
                409, "workspace_unavailable", "The workspace is archived or unavailable."
            ) from exc
        return conversation_view(record)

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
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
        return conversation_view(record, active_run=active)

    def delete_conversation(self, conversation_id: str) -> None:
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
        try:
            records = self.persistence.list_messages(conversation_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(
                404, "conversation_not_found", "Conversation was not found."
            ) from exc
        return [message_view(item) for item in records]


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


__all__ = ["CatalogService"]
