"""Small SQLite repository with short-lived connections and transactions."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator

from clearloop.memory.models import MemoryKind, MemorySource, StoredMemory


class MemoryRepositoryError(RuntimeError):
    """Base class for persistence failures safe to translate at outer layers."""


class MemoryDuplicateError(MemoryRepositoryError):
    pass


class MemoryCapacityError(MemoryRepositoryError):
    pass


class MemoryNotFoundError(MemoryRepositoryError):
    pass


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class MemoryRepository:
    """Persist memory entries without retaining a connection between calls."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve(strict=False)

    def initialize(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection, connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version not in {0, 1}:
                    raise MemoryRepositoryError(
                        "Memory storage uses an unsupported schema version."
                    )
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_entries (
                        id TEXT PRIMARY KEY,
                        workspace_key TEXT NOT NULL,
                        kind TEXT NOT NULL CHECK(kind IN ('preference','fact','decision','note')),
                        content TEXT NOT NULL,
                        source TEXT NOT NULL CHECK(source IN ('manual','run_result')),
                        source_run_id TEXT,
                        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                        pinned INTEGER NOT NULL CHECK(pinned IN (0,1)),
                        content_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(workspace_key, content_hash)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS ix_memory_workspace_updated
                    ON memory_entries(workspace_key, updated_at DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS ix_memory_workspace_enabled
                    ON memory_entries(workspace_key, enabled, pinned DESC, updated_at DESC)
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(memory_entries)")
                }
                required_columns = {
                    "id",
                    "workspace_key",
                    "kind",
                    "content",
                    "source",
                    "source_run_id",
                    "enabled",
                    "pinned",
                    "content_hash",
                    "created_at",
                    "updated_at",
                }
                if not required_columns.issubset(columns):
                    raise MemoryRepositoryError("Memory storage schema is invalid.")
                if version == 0:
                    connection.execute("PRAGMA user_version=1")
        except (OSError, sqlite3.Error) as exc:
            raise MemoryRepositoryError("Memory storage could not be initialized.") from exc

    def list(self, workspace_key: str, *, enabled_only: bool = False) -> list[StoredMemory]:
        query = "SELECT * FROM memory_entries WHERE workspace_key = ?"
        parameters: tuple[object, ...] = (workspace_key,)
        if enabled_only:
            query += " AND enabled = 1"
        query += " ORDER BY pinned DESC, updated_at DESC, id ASC"
        try:
            with self._connection() as connection:
                rows = connection.execute(query, parameters).fetchall()
        except sqlite3.Error as exc:
            raise MemoryRepositoryError("Memory entries could not be read.") from exc
        return [self._decode(row) for row in rows]

    def get(self, workspace_key: str, memory_id: str) -> StoredMemory:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM memory_entries WHERE workspace_key = ? AND id = ?",
                    (workspace_key, memory_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise MemoryRepositoryError("The memory entry could not be read.") from exc
        if row is None:
            raise MemoryNotFoundError("Memory entry was not found.")
        return self._decode(row)

    def create(
        self,
        *,
        memory_id: str,
        workspace_key: str,
        kind: MemoryKind,
        content: str,
        source: MemorySource,
        source_run_id: str | None,
        pinned: bool,
        content_hash: str,
        max_items: int,
    ) -> StoredMemory:
        record: StoredMemory | None = None
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                timestamp = _utc_now_text()
                count = connection.execute(
                    "SELECT COUNT(*) FROM memory_entries WHERE workspace_key = ?",
                    (workspace_key,),
                ).fetchone()[0]
                if count >= max_items:
                    raise MemoryCapacityError("The workspace memory limit has been reached.")
                connection.execute(
                    """
                    INSERT INTO memory_entries (
                        id, workspace_key, kind, content, source, source_run_id,
                        enabled, pinned, content_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        workspace_key,
                        kind.value,
                        content,
                        source.value,
                        source_run_id,
                        int(pinned),
                        content_hash,
                        timestamp,
                        timestamp,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM memory_entries WHERE workspace_key = ? AND id = ?",
                    (workspace_key, memory_id),
                ).fetchone()
                if row is None:
                    raise MemoryRepositoryError("The created memory entry could not be read.")
                record = self._decode(row)
        except MemoryCapacityError:
            raise
        except sqlite3.IntegrityError as exc:
            raise MemoryDuplicateError("An equivalent memory entry already exists.") from exc
        except sqlite3.Error as exc:
            raise MemoryRepositoryError("The memory entry could not be created.") from exc
        assert record is not None
        return record

    def update(
        self,
        workspace_key: str,
        memory_id: str,
        changes: Mapping[str, object],
    ) -> StoredMemory:
        allowed = {"kind", "content", "pinned", "enabled", "content_hash"}
        invalid = set(changes).difference(allowed)
        if invalid or not changes:
            raise ValueError("changes must contain supported fields")
        assignments: list[str] = []
        parameters: list[object] = []
        for name in ("kind", "content", "pinned", "enabled", "content_hash"):
            if name not in changes:
                continue
            value = changes[name]
            if isinstance(value, MemoryKind):
                value = value.value
            if name in {"pinned", "enabled"}:
                value = int(bool(value))
            assignments.append(f"{name} = ?")
            parameters.append(value)
        assignments.append("updated_at = ?")
        record: StoredMemory | None = None
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                write_parameters = [
                    *parameters,
                    _utc_now_text(),
                    workspace_key,
                    memory_id,
                ]
                cursor = connection.execute(
                    f"UPDATE memory_entries SET {', '.join(assignments)} "
                    "WHERE workspace_key = ? AND id = ?",
                    tuple(write_parameters),
                )
                if cursor.rowcount == 0:
                    raise MemoryNotFoundError("Memory entry was not found.")
                row = connection.execute(
                    "SELECT * FROM memory_entries WHERE workspace_key = ? AND id = ?",
                    (workspace_key, memory_id),
                ).fetchone()
                if row is None:
                    raise MemoryRepositoryError("The updated memory entry could not be read.")
                record = self._decode(row)
        except MemoryNotFoundError:
            raise
        except sqlite3.IntegrityError as exc:
            raise MemoryDuplicateError("An equivalent memory entry already exists.") from exc
        except sqlite3.Error as exc:
            raise MemoryRepositoryError("The memory entry could not be updated.") from exc
        assert record is not None
        return record

    def delete(self, workspace_key: str, memory_id: str) -> None:
        try:
            with self._connection() as connection, connection:
                cursor = connection.execute(
                    "DELETE FROM memory_entries WHERE workspace_key = ? AND id = ?",
                    (workspace_key, memory_id),
                )
                if cursor.rowcount == 0:
                    raise MemoryNotFoundError("Memory entry was not found.")
        except MemoryNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise MemoryRepositoryError("The memory entry could not be deleted.") from exc

    def purge(self, workspace_key: str) -> int:
        try:
            with self._connection() as connection, connection:
                cursor = connection.execute(
                    "DELETE FROM memory_entries WHERE workspace_key = ?", (workspace_key,)
                )
                return max(0, cursor.rowcount)
        except sqlite3.Error as exc:
            raise MemoryRepositoryError("Workspace memory could not be cleared.") from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.database_path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise MemoryRepositoryError("Memory storage is unavailable.") from exc
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> StoredMemory:
        return StoredMemory(
            id=str(row["id"]),
            workspace_key=str(row["workspace_key"]),
            kind=MemoryKind(str(row["kind"])),
            content=str(row["content"]),
            source=MemorySource(str(row["source"])),
            source_run_id=(str(row["source_run_id"]) if row["source_run_id"] is not None else None),
            enabled=bool(row["enabled"]),
            pinned=bool(row["pinned"]),
            content_hash=str(row["content_hash"]),
            created_at=_parse_datetime(str(row["created_at"])),
            updated_at=_parse_datetime(str(row["updated_at"])),
        )

    @classmethod
    def _decode(cls, row: sqlite3.Row) -> StoredMemory:
        try:
            return cls._record(row)
        except (IndexError, KeyError, OverflowError, TypeError, ValueError) as exc:
            raise MemoryRepositoryError("Memory storage contains invalid data.") from exc


__all__ = [
    "MemoryCapacityError",
    "MemoryDuplicateError",
    "MemoryNotFoundError",
    "MemoryRepository",
    "MemoryRepositoryError",
]
