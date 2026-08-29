"""实现受工作区策略约束的只读目录浏览器。"""

from __future__ import annotations

import os

from coding_agent.agents.security import WorkspacePolicy, WorkspacePolicyError

from .errors import ApplicationError


class DirectoryBrowser:
    """列出允许根目录下的文件夹，且不跟随任何越界链接。"""

    def __init__(self, policy: WorkspacePolicy, *, max_entries: int = 500) -> None:
        """初始化受限目录浏览器。

        :param policy: 校验路径是否位于允许根目录内的策略。
        :param max_entries: 单次最多返回的直接子目录数。
        """

        # 策略控制边界，数量上限避免巨大目录拖垮 API 响应。
        self.policy = policy
        self.max_entries = max_entries

    def browse(self, value: str | None = None) -> dict[str, object]:
        """列出经过策略校验的直接子目录，并返回安全的父目录导航。

        :param value: 待浏览目录路径；None 表示允许根目录。
        :return: 当前目录、边界内父目录、允许根目录和子目录列表。
        :raises ApplicationError: 路径越界、无效或服务进程无法读取目录。
        """

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
