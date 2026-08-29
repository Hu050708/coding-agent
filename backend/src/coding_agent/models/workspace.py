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
class Workspace(TimestampMixin, SoftDeleteMixin, Base):
    """可登记并承载会话、运行和记忆的规范工作区。"""

    __tablename__ = "workspaces"

    # 工作区主键。
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # 经过安全策略校验和解析的绝对路径。
    canonical_path: Mapped[str] = mapped_column(Text, nullable=False)
    # 用于跨大小写文件系统比较和唯一约束的规范路径键。
    path_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    # 用户可见的工作区名称。
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 工作区归档时间；为 None 表示仍在活动目录中。
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 工作区下的会话 ORM 集合。
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="workspace")
    # 工作区下的项目记忆 ORM 集合。
    memory_entries: Mapped[list["MemoryEntry"]] = relationship(back_populates="workspace")

    __table_args__ = (
        CheckConstraint("length(path_key) > 0", name="path_key_not_blank"),
        CheckConstraint("length(display_name) > 0", name="display_name_not_blank"),
        Index(
            "uq_workspaces_path_key_live",
            "path_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_workspaces_live_updated", "deleted_at", "archived_at", "updated_at"),
    )

