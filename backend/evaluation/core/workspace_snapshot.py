"""使用文件哈希记录评测工作区在 Agent 运行前后的变化。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .contracts import WorkspaceChanges


_IGNORED_PARTS = {
    ".coding-agent-traces",
    ".pytest_cache",
    "__pycache__",
}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    """相对文件路径到 SHA-256 的稳定映射。"""

    files: dict[str, str]

    @classmethod
    def capture(cls, root: Path) -> "WorkspaceSnapshot":
        """扫描一个小型合成任务工作区并计算文件摘要。"""

        files: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if (
                not path.is_file()
                or any(part in _IGNORED_PARTS for part in relative.parts)
                or path.suffix.casefold() in _IGNORED_SUFFIXES
            ):
                continue
            files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return cls(files)

    @property
    def digest(self) -> str:
        """:return: 同时覆盖路径和内容的整个模板摘要。"""

        digest = hashlib.sha256()
        for path, file_hash in sorted(self.files.items()):
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_hash.encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()

    def changes_to(self, current: "WorkspaceSnapshot") -> WorkspaceChanges:
        """比较运行后的快照，返回新增、修改和删除路径。"""

        before = set(self.files)
        after = set(current.files)
        return WorkspaceChanges(
            added=tuple(sorted(after - before)),
            modified=tuple(
                sorted(path for path in before & after if self.files[path] != current.files[path])
            ),
            deleted=tuple(sorted(before - after)),
        )


__all__ = ["WorkspaceSnapshot"]
