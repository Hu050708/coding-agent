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

    # 运行主键。
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # 本次运行作用的工作区外键。
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    # 本次运行所属会话的外键。
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    # 客户端生成的幂等请求标识，同一会话内唯一。
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # 本次运行实际采用的命令权限模式。
    permission_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    # 本次运行是否使用项目记忆。
    use_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 当前持久化运行状态。
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RunStatus.STARTING.value
    )
    # 实际调用的模型名称；运行开始前可以为空。
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 正常终止、取消或预算耗尽的机器可读原因。
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 运行失败时的稳定错误码。
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 已清洗、可安全展示的失败说明。
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # 累计输入模型的 token 数。
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 累计由模型生成的 token 数。
    completion_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 累计总 token 数。
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 命中供应商提示缓存的输入 token 数。
    prompt_cache_hit_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 未命中供应商提示缓存的输入 token 数。
    prompt_cache_miss_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 已完成的模型调用次数。
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 已尝试的工具调用次数。
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 运行总耗时（毫秒）。
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Agent 实际开始执行的时间。
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 运行进入终态的时间。
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 首次收到取消请求的时间。
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 运行所使用工作区的 ORM 关系。
    workspace: Mapped[Workspace] = relationship()
    # 运行所属会话的 ORM 关系。
    conversation: Mapped[Conversation] = relationship(back_populates="runs")
    # 与运行关联的输入和输出消息。
    messages: Mapped[list["Message"]] = relationship(back_populates="run")
    # 按序号排列、支持 SSE 重放的安全事件。
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", order_by="RunEvent.seq", cascade="all, delete-orphan"
    )
    # 运行产生的危险操作审批记录。
    approvals: Mapped[list["Approval"]] = relationship(back_populates="run")
    # 按上下文位置排列的不可变记忆快照。
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

    # 消息主键。
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # 消息所属会话的外键。
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    # 产生或消费该消息的运行；普通历史消息可为空。
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True
    )
    # 消息在会话内的单调递增序号。
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 用户或助手角色；不持久化系统和工具消息。
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # 用户可见的消息正文。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 消息写入数据库的时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 消息所属会话的 ORM 关系。
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    # 消息关联运行的可选 ORM 关系。
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

    # 事件所属运行 ID，也是联合主键的一部分。
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    # 事件在运行内的单调递增序号。
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 稳定事件类型名称。
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    # 经过白名单清洗、可安全持久化和推送的数据。
    data: Mapped[dict[str, Any]] = mapped_column(SAFE_JSON, nullable=False, default=dict)
    # 事件发生的数据库服务器时间。
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 事件所属运行的 ORM 关系。
    run: Mapped[Run] = relationship(back_populates="events")

    __table_args__ = (
        CheckConstraint("seq > 0", name="seq_positive"),
        CheckConstraint("length(event) > 0", name="event_not_blank"),
        Index("ix_run_events_occurred", "occurred_at"),
    )


class Approval(TimestampMixin, Base):
    """危险工具操作的一次性用户审批。"""

    __tablename__ = "approvals"

    # 审批请求主键。
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # 触发审批的运行外键。
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    # 待处理、同意、拒绝、过期或取消状态。
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    # 请求执行的工具名称。
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 面向用户的简短操作摘要。
    action_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    # 工具为何需要审批的安全策略说明。
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    # 此处只能保存 safe_approval_data 返回的白名单安全展示对象。
    request_data: Mapped[dict[str, Any]] = mapped_column(SAFE_JSON, nullable=False, default=dict)
    # 审批自动失效的时间。
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 用户决定或系统取消审批的时间。
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 审批所属运行的 ORM 关系。
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

