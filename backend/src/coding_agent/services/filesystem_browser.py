"""实现受工作区策略约束的只读目录浏览器。"""

from __future__ import annotations

import os
from pathlib import Path

from coding_agent.agents.security import WorkspacePolicy, WorkspacePolicyError

from .errors import ApplicationError


class DirectoryBrowser:
    """列出允许根目录下的文件夹，且不跟随任何越界链接。"""

    def __init__(self, policy: WorkspacePolicy, *, max_entries: int = 500) -> None:
        self.policy = policy
        self.max_entries = max_entries

    def browse(self, value: str | None = None) -> dict[str, object]:
        """列出经过策略校验的直接子目录，并返回安全的父目录导航。"""

        # 第一步：规范化请求目录，并在读取前确认其位于允许根目录内。
        requested = os.fspath(self.policy.allowed_root) if value is None else value
        try:
            current = self.policy.validate(requested)
        except WorkspacePolicyError as exc:
            raise ApplicationError(400, exc.code, exc.message) from exc

        entries: list[dict[str, str]] = []
        try:
            candidates = sorted(current.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise ApplicationError(
                403,
                "directory_unavailable",
                "This directory cannot be read by the server process.",
            ) from exc

        # 第二步：逐项重新解析，只保留未越界的目录且限制返回数量。
        for candidate in candidates:
            if len(entries) >= self.max_entries:
                break
            try:
                resolved = self.policy.validate(os.fspath(candidate))
            except WorkspacePolicyError:
                continue
            entries.append({"name": candidate.name, "path": os.fspath(resolved)})

        # 第三步：父目录同样经过策略校验，根目录本身不提供向上导航。
        root = self.policy.allowed_root
        parent: str | None = None
        if current != root:
            candidate_parent = current.parent
            try:
                parent = os.fspath(self.policy.validate(os.fspath(candidate_parent)))
            except WorkspacePolicyError:
                parent = os.fspath(root)
        return {
            "current_path": os.fspath(current),
            "parent_path": parent,
            "allowed_root": os.fspath(root),
            "entries": entries,
        }


__all__ = ["DirectoryBrowser"]
