"""SQLAlchemy 实体模型。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin
from .enums import PermissionMode

if TYPE_CHECKING:
    from .run import Message, Run
    from .workspace import Workspace


class Conversation(TimestampMixin, SoftDeleteMixin, Base):
    """工作区内按消息序号维护上下文的持久化会话。"""

    __tablename__ = "conversations"

    # 会话主键。
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # 会话所属工作区的外键。
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    # 用户可见的会话标题。
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # 创建运行时默认采用的命令权限模式。
    default_permission_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PermissionMode.AGENT.value
    )
    # 新运行默认是否装载项目记忆。
    use_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 下一条消息应占用的单调递增序号。
    next_message_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    # 会话归档时间；为 None 表示未归档。
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 会话所属工作区的 ORM 关系。
    workspace: Mapped[Workspace] = relationship(back_populates="conversations")
    # 会话创建过的所有运行。
    runs: Mapped[list["Run"]] = relationship(back_populates="conversation")
    # 按序号排列的用户与助手消息。
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

