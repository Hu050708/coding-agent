"""SQLAlchemy 实体模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SAFE_JSON, SoftDeleteMixin, TimestampMixin
from .enums import PermissionMode, RunStatus
class MemoryEntry(TimestampMixin, SoftDeleteMixin, Base):
    """可启用、置顶并按内容去重的工作区记忆。"""

    __tablename__ = "memory_entries"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    source_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="memory_entries")
    snapshots: Mapped[list["RunMemory"]] = relationship(back_populates="memory_entry")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('preference','fact','decision','note')", name="kind_valid"
        ),
        CheckConstraint("source IN ('manual','run_result')", name="source_valid"),
        CheckConstraint("length(content) > 0", name="content_not_blank"),
        CheckConstraint("length(content) <= 2000", name="content_size_valid"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_sha256"),
        Index(
            "uq_memory_entries_workspace_hash_live",
            "workspace_id",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_memory_entries_workspace_enabled",
            "workspace_id",
            "deleted_at",
            "enabled",
            "pinned",
            "updated_at",
        ),
    )


class RunMemory(Base):
    """为一次运行冻结并实际提供给模型的不可变记忆。"""

    __tablename__ = "run_memories"

    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    memory_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("memory_entries.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship(back_populates="memories")
    memory_entry: Mapped[MemoryEntry | None] = relationship(back_populates="snapshots")

    __table_args__ = (
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint(
            "kind IN ('preference','fact','decision','note')", name="kind_valid"
        ),
        CheckConstraint("length(content) > 0", name="content_not_blank"),
        CheckConstraint("length(content) <= 2000", name="content_size_valid"),
    )


