"""SQLAlchemy 实体模型。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from .run import Run
    from .workspace import Workspace


class MemoryEntry(TimestampMixin, SoftDeleteMixin, Base):
    """可启用、置顶并按内容去重的工作区记忆。"""

    __tablename__ = "memory_entries"

    # 记忆条目主键。
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # 记忆所属工作区的外键。
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    # 记忆的业务分类。
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # 用户确认过、可供模型参考的正文。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 规范化正文的 SHA-256 哈希，用于活动条目去重。
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 条目来源，例如人工创建或运行结果。
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    # 自动生成条目所关联的运行；来源运行删除后允许置空。
    source_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    # 是否在构建有限快照时优先选择。
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 是否允许用于后续 Agent 运行。
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 用户确认该条记忆可以保存的时间。
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 条目所属工作区的 ORM 关系。
    workspace: Mapped[Workspace] = relationship(back_populates="memory_entries")
    # 历次运行对该条目的不可变快照引用。
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

    # 使用该记忆快照的运行 ID，也是联合主键的一部分。
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    # 该条记忆在本次运行上下文中的一基顺序。
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 原记忆条目 ID；原条目删除后保留快照并置空引用。
    memory_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("memory_entries.id", ondelete="SET NULL"), nullable=True
    )
    # 快照时冻结的记忆分类。
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # 快照时冻结的正文，后续编辑原条目不会改变它。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 记忆被捕获进运行上下文的时间。
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 快照所属运行的 ORM 关系。
    run: Mapped[Run] = relationship(back_populates="memories")
    # 可选的原始记忆条目 ORM 关系。
    memory_entry: Mapped[MemoryEntry | None] = relationship(back_populates="snapshots")

    __table_args__ = (
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint(
            "kind IN ('preference','fact','decision','note')", name="kind_valid"
        ),
        CheckConstraint("length(content) > 0", name="content_not_blank"),
        CheckConstraint("length(content) <= 2000", name="content_size_valid"),
    )

