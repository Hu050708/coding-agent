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
class Run(TimestampMixin, SoftDeleteMixin, Base):
    """一次智能体执行的状态、预算、结果和错误投影。"""

    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    permission_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    use_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RunStatus.STARTING.value
    )
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    prompt_cache_hit_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    prompt_cache_miss_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    workspace: Mapped[Workspace] = relationship()
    conversation: Mapped[Conversation] = relationship(back_populates="runs")
    messages: Mapped[list["Message"]] = relationship(back_populates="run")
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", order_by="RunEvent.seq", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["Approval"]] = relationship(back_populates="run")
    memories: Mapped[list["RunMemory"]] = relationship(
        back_populates="run", order_by="RunMemory.position", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "client_request_id", name="uq_runs_conversation_client_request"
        ),
        CheckConstraint("length(client_request_id) > 0", name="client_request_id_not_blank"),
        CheckConstraint(
            "permission_mode IN ('ask','agent','workspace_full')", name="permission_mode_valid"
        ),
        CheckConstraint(
            "status IN ('starting','running','waiting_approval','cancelling','completed',"
            "'failed','cancelled','budget_exhausted','interrupted')",
            name="status_valid",
        ),
        CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0 AND total_tokens >= 0 AND "
            "prompt_cache_hit_tokens >= 0 AND prompt_cache_miss_tokens >= 0 AND "
            "model_calls >= 0 AND tool_calls >= 0",
            name="counters_non_negative",
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_non_negative"),
        Index(
            "uq_runs_one_active_per_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text(
                "status IN ('starting','running','waiting_approval','cancelling') "
                "AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "status IN ('starting','running','waiting_approval','cancelling') "
                "AND deleted_at IS NULL"
            ),
        ),
        Index("ix_runs_conversation_created", "conversation_id", "created_at"),
        Index("ix_runs_workspace_created", "workspace_id", "created_at"),
    )


class Message(SoftDeleteMixin, Base):
    """会话中的用户或助手消息。"""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    run: Mapped[Run | None] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
        CheckConstraint("seq > 0", name="seq_positive"),
        CheckConstraint("role IN ('user','assistant')", name="role_visible"),
        CheckConstraint("length(content) > 0", name="content_not_blank"),
        Index("ix_messages_conversation_live_seq", "conversation_id", "deleted_at", "seq"),
    )


class RunEvent(Base):
    """用于 SSE 断线续传的不可变运行事件。"""

    __tablename__ = "run_events"

    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(SAFE_JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship(back_populates="events")

    __table_args__ = (
        CheckConstraint("seq > 0", name="seq_positive"),
        CheckConstraint("length(event) > 0", name="event_not_blank"),
        Index("ix_run_events_occurred", "occurred_at"),
    )


class Approval(TimestampMixin, Base):
    """危险工具操作的一次性用户审批。"""

    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    action_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    # 此处只能保存 safe_approval_data 返回的白名单安全展示对象。
    request_data: Mapped[dict[str, Any]] = mapped_column(SAFE_JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship(back_populates="approvals")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired','cancelled')",
            name="status_valid",
        ),
        CheckConstraint("length(tool_name) > 0", name="tool_name_not_blank"),
        CheckConstraint("length(action_summary) > 0", name="action_summary_not_blank"),
        Index(
            "uq_approvals_one_pending_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )


