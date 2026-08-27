"""Workspace validation, memory policy, and deterministic retrieval."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from coding_agent.memory.models import (
    MemoryEntry,
    MemoryKind,
    MemorySnapshot,
    MemorySource,
    StoredMemory,
)
from coding_agent.memory.repository import (
    MemoryCapacityError,
    MemoryDuplicateError,
    MemoryNotFoundError,
    MemoryRepository,
    MemoryRepositoryError,
)
from coding_agent.security import WorkspacePolicy, WorkspacePolicyError


MAX_MEMORY_CONTENT_CHARS = 2_000
MAX_MEMORIES_PER_WORKSPACE = 500
DEFAULT_SNAPSHOT_ITEMS = 8
DEFAULT_SNAPSHOT_CHARS = 6_000


class MemoryServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class MemoryService:
    """Expose workspace-scoped operations over an isolated repository key."""

    def __init__(
        self,
        repository: MemoryRepository,
        workspace_policy: WorkspacePolicy,
        *,
        max_items: int = MAX_MEMORIES_PER_WORKSPACE,
        snapshot_items: int = DEFAULT_SNAPSHOT_ITEMS,
        snapshot_chars: int = DEFAULT_SNAPSHOT_CHARS,
    ) -> None:
        if max_items < 1 or snapshot_items < 1 or snapshot_chars < 1:
            raise ValueError("memory limits must be positive")
        self.repository = repository
        self.workspace_policy = workspace_policy
        self.max_items = max_items
        self.snapshot_items = snapshot_items
        self.snapshot_chars = snapshot_chars

    def list(self, workspace: str) -> list[MemoryEntry]:
        resolved, key = self._workspace(workspace)
        try:
            records = self.repository.list(key)
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc
        return [self._entry(resolved, record) for record in records]

    def create(
        self,
        *,
        workspace: str,
        kind: MemoryKind | str,
        content: str,
        pinned: bool = False,
        source: MemorySource | str = MemorySource.MANUAL,
        source_run_id: str | None = None,
    ) -> MemoryEntry:
        resolved, key = self._workspace(workspace)
        safe_kind = self._kind(kind)
        safe_source = self._source(source)
        safe_content = self._content(content)
        if safe_source is MemorySource.MANUAL:
            source_run_id = None
        else:
            source_run_id = self._source_run_id(source_run_id)
        try:
            record = self.repository.create(
                memory_id=uuid4().hex,
                workspace_key=key,
                kind=safe_kind,
                content=safe_content,
                source=safe_source,
                source_run_id=source_run_id,
                pinned=bool(pinned),
                content_hash=self._content_hash(safe_content),
                max_items=self.max_items,
            )
        except MemoryDuplicateError as exc:
            raise MemoryServiceError(
                "memory_duplicate", "An equivalent memory entry already exists.", status_code=409
            ) from exc
        except MemoryCapacityError as exc:
            raise MemoryServiceError(
                "memory_capacity_reached",
                "The workspace memory limit has been reached.",
                status_code=409,
            ) from exc
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc
        return self._entry(resolved, record)

    def update(
        self,
        *,
        workspace: str,
        memory_id: str,
        kind: MemoryKind | str | None = None,
        content: str | None = None,
        pinned: bool | None = None,
        enabled: bool | None = None,
    ) -> MemoryEntry:
        resolved, key = self._workspace(workspace)
        changes: dict[str, object] = {}
        if kind is not None:
            changes["kind"] = self._kind(kind)
        if content is not None:
            safe_content = self._content(content)
            changes["content"] = safe_content
            changes["content_hash"] = self._content_hash(safe_content)
        if pinned is not None:
            changes["pinned"] = bool(pinned)
        if enabled is not None:
            changes["enabled"] = bool(enabled)
        if not changes:
            raise MemoryServiceError(
                "memory_update_empty", "At least one memory field must be updated.", status_code=422
            )
        try:
            record = self.repository.update(key, self._id(memory_id), changes)
        except MemoryNotFoundError as exc:
            raise MemoryServiceError(
                "memory_not_found", "Memory entry was not found.", status_code=404
            ) from exc
        except MemoryDuplicateError as exc:
            raise MemoryServiceError(
                "memory_duplicate", "An equivalent memory entry already exists.", status_code=409
            ) from exc
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc
        return self._entry(resolved, record)

    def delete(self, *, workspace: str, memory_id: str) -> None:
        _, key = self._workspace(workspace)
        try:
            self.repository.delete(key, self._id(memory_id))
        except MemoryNotFoundError as exc:
            raise MemoryServiceError(
                "memory_not_found", "Memory entry was not found.", status_code=404
            ) from exc
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc

    def purge(self, *, workspace: str) -> int:
        _, key = self._workspace(workspace)
        try:
            return self.repository.purge(key)
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc

    def snapshot(self, *, workspace: str | Path, task: str) -> MemorySnapshot:
        resolved, key = self._workspace(os.fspath(workspace))
        try:
            records = self.repository.list(key, enabled_only=True)
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc
        if not records:
            return MemorySnapshot(status="empty")

        task_tokens = _tokens(task)
        ranked = sorted(
            records,
            key=lambda item: (
                -int(item.pinned),
                -len(task_tokens.intersection(_tokens(item.content))),
                -item.updated_at.timestamp(),
                item.id,
            ),
        )
        selected: list[MemoryEntry] = []
        used_chars = 0
        for record in ranked:
            if len(selected) >= self.snapshot_items:
                break
            content_chars = len(record.content)
            if used_chars + content_chars > self.snapshot_chars:
                continue
            selected.append(self._entry(resolved, record))
            used_chars += content_chars
        if not selected:
            return MemorySnapshot(status="empty")
        return MemorySnapshot(status="loaded", entries=tuple(selected))

    def _workspace(self, workspace: str) -> tuple[Path, str]:
        try:
            resolved = self.workspace_policy.validate(workspace)
        except WorkspacePolicyError as exc:
            raise MemoryServiceError(exc.code, exc.message, status_code=400) from exc
        normalized = os.path.normcase(os.path.abspath(os.fspath(resolved)))
        key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return resolved, key

    @staticmethod
    def _entry(workspace: Path, record: StoredMemory) -> MemoryEntry:
        return MemoryEntry(
            id=record.id,
            workspace=os.fspath(workspace),
            kind=record.kind,
            content=record.content,
            source=record.source,
            source_run_id=record.source_run_id,
            pinned=record.pinned,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _content(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise MemoryServiceError(
                "memory_content_invalid", "Memory content must be non-empty text.", status_code=422
            )
        content = value.strip()
        if len(content) > MAX_MEMORY_CONTENT_CHARS:
            raise MemoryServiceError(
                "memory_content_too_large",
                f"Memory content must not exceed {MAX_MEMORY_CONTENT_CHARS} characters.",
                status_code=413,
            )
        if "\x00" in content:
            raise MemoryServiceError(
                "memory_content_invalid", "Memory content is malformed.", status_code=422
            )
        return content

    @staticmethod
    def _content_hash(content: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", content).casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _kind(value: MemoryKind | str) -> MemoryKind:
        try:
            return value if isinstance(value, MemoryKind) else MemoryKind(value)
        except (TypeError, ValueError) as exc:
            raise MemoryServiceError(
                "memory_kind_invalid", "Memory kind is invalid.", status_code=422
            ) from exc

    @staticmethod
    def _source(value: MemorySource | str) -> MemorySource:
        try:
            return value if isinstance(value, MemorySource) else MemorySource(value)
        except (TypeError, ValueError) as exc:
            raise MemoryServiceError(
                "memory_source_invalid", "Memory source is invalid.", status_code=422
            ) from exc

    @staticmethod
    def _id(value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 128:
            raise MemoryServiceError(
                "memory_not_found", "Memory entry was not found.", status_code=404
            )
        return value

    @staticmethod
    def _source_run_id(value: str | None) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 128
            or "\x00" in value
            or any(ord(character) < 32 for character in value)
        ):
            raise MemoryServiceError(
                "memory_source_run_invalid",
                "A valid completed source run is required.",
                status_code=422,
            )
        return value

    @staticmethod
    def _unavailable(_exc: Exception) -> MemoryServiceError:
        return MemoryServiceError(
            "memory_store_unavailable", "Project memory storage is unavailable.", status_code=503
        )


_WORD_OR_CJK = re.compile(r"[a-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]+", re.IGNORECASE)


def _tokens(value: str) -> frozenset[str]:
    tokens: set[str] = set()
    for match in _WORD_OR_CJK.findall(unicodedata.normalize("NFKC", value).casefold()):
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", match):
            characters = tuple(match)
            tokens.update(characters)
            tokens.update("".join(characters[index : index + 2]) for index in range(len(characters) - 1))
        else:
            tokens.add(match)
    return frozenset(tokens)


__all__ = [
    "DEFAULT_SNAPSHOT_CHARS",
    "DEFAULT_SNAPSHOT_ITEMS",
    "MAX_MEMORIES_PER_WORKSPACE",
    "MAX_MEMORY_CONTENT_CHARS",
    "MemoryService",
    "MemoryServiceError",
]
