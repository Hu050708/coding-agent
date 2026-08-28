"""Web 编排和记忆服务共享的服务端工作区白名单。"""

from __future__ import annotations

import os
from pathlib import Path


class WorkspacePolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


class WorkspacePolicy:
    """仅允许配置根目录内已经存在的文件夹。"""

    def __init__(self, allowed_root: str | os.PathLike[str]) -> None:
        try:
            root = Path(allowed_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspacePolicyError(
                "allowed_root_invalid", "The configured workspace root is unavailable."
            ) from exc
        if not root.is_dir():
            raise WorkspacePolicyError(
                "allowed_root_invalid", "The configured workspace root is not a directory."
            )
        self.allowed_root = root

    def validate(self, value: str) -> Path:
        """返回白名单根目录内已存在工作区的规范绝对路径。"""

        # 第一步：检查输入形式并要求用户显式提供绝对路径。
        if not isinstance(value, str) or not value.strip():
            raise WorkspacePolicyError("workspace_invalid", "Workspace must be a non-empty path.")
        if len(value) > 1024 or "\x00" in value or any(ord(character) < 32 for character in value):
            raise WorkspacePolicyError("workspace_invalid", "Workspace path is malformed.")
        candidate = Path(value.strip()).expanduser()
        if not candidate.is_absolute():
            raise WorkspacePolicyError("workspace_not_absolute", "Workspace must be an absolute path.")
        # 第二步：解析链接后的真实路径，并确认目标是现有目录。
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspacePolicyError("workspace_not_found", "Workspace directory does not exist.") from exc
        if not resolved.is_dir():
            raise WorkspacePolicyError("workspace_not_directory", "Workspace must be a directory.")
        # 第三步：比较规范路径的公共前缀，拒绝跨盘符或白名单之外的目录。
        try:
            common = os.path.commonpath((_normalized(self.allowed_root), _normalized(resolved)))
        except ValueError as exc:
            raise WorkspacePolicyError(
                "workspace_not_allowed", "Workspace is outside the configured root."
            ) from exc
        if common != _normalized(self.allowed_root):
            raise WorkspacePolicyError(
                "workspace_not_allowed", "Workspace is outside the configured root."
            )
        return resolved


__all__ = ["WorkspacePolicy", "WorkspacePolicyError"]
