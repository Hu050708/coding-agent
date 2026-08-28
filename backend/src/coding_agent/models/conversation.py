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
class Conversation(TimestampMixin, SoftDeleteMixin, Base):
    """工作区内按消息序号维护上下文的持久化会话。"""

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    default_permission_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PermissionMode.AGENT.value
    )
    use_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_message_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped[Workspace] = relationship(back_populates="conversations")
    runs: Mapped[list["Run"]] = relationship(back_populates="conversation")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.seq"
    )

    __table_args__ = (
        CheckConstraint("length(title) > 0", name="title_not_blank"),
        CheckConstraint(
            "default_permission_mode IN ('ask','agent','workspace_full')",
            name="permission_mode_valid",
        ),
        CheckConstraint("next_message_seq > 0", name="next_message_seq_positive"),
        Index(
            "ix_conversations_workspace_live_updated",
            "workspace_id",
            "deleted_at",
            "archived_at",
            "updated_at",
        ),
    )


