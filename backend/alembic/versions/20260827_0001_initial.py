"""创建 Coding Agent Web 服务的持久化数据库结构。

Revision ID: 20260827_0001
Revises:
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260827_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    """创建所有可更新时间实体共用的时间戳列。

    :return: 数据库生成的 ``created_at`` 和 ``updated_at`` 列定义。
    """

    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    """按外键依赖顺序创建全部持久化表、约束和查询索引。"""

    # 第一步：创建工作区、会话和运行三层生命周期主表。
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_path", sa.Text(), nullable=False),
        sa.Column("path_key", sa.String(length=2048), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(display_name) > 0", name=op.f("ck_workspaces_display_name_not_blank")
        ),
        sa.CheckConstraint(
            "length(path_key) > 0", name=op.f("ck_workspaces_path_key_not_blank")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
    )
    op.create_index(
        "ix_workspaces_live_updated",
        "workspaces",
        ["deleted_at", "archived_at", "updated_at"],
        unique=False,
    )
    op.create_index(
        "uq_workspaces_path_key_live",
        "workspaces",
        ["path_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("default_permission_mode", sa.String(length=24), nullable=False),
        sa.Column("use_memory", sa.Boolean(), nullable=False),
        sa.Column("next_message_seq", sa.BigInteger(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "default_permission_mode IN ('review','workspace','auto')",
            name=op.f("ck_conversations_permission_mode_valid"),
        ),
        sa.CheckConstraint(
            "next_message_seq > 0",
            name=op.f("ck_conversations_next_message_seq_positive"),
        ),
        sa.CheckConstraint(
            "length(title) > 0", name=op.f("ck_conversations_title_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_conversations_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index(
        "ix_conversations_workspace_live_updated",
        "conversations",
        ["workspace_id", "deleted_at", "archived_at", "updated_at"],
        unique=False,
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("client_request_id", sa.String(length=128), nullable=False),
        sa.Column("permission_mode", sa.String(length=24), nullable=False),
        sa.Column("use_memory", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False),
        sa.Column("prompt_cache_hit_tokens", sa.BigInteger(), nullable=False),
        sa.Column("prompt_cache_miss_tokens", sa.BigInteger(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(client_request_id) > 0",
            name=op.f("ck_runs_client_request_id_not_blank"),
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0 AND total_tokens >= 0 AND "
            "prompt_cache_hit_tokens >= 0 AND prompt_cache_miss_tokens >= 0 AND "
            "model_calls >= 0 AND tool_calls >= 0",
            name=op.f("ck_runs_counters_non_negative"),
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name=op.f("ck_runs_duration_non_negative"),
        ),
        sa.CheckConstraint(
            "permission_mode IN ('review','workspace','auto')",
            name=op.f("ck_runs_permission_mode_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('starting','running','waiting_approval','cancelling','completed',"
            "'failed','cancelled','budget_exhausted','interrupted')",
            name=op.f("ck_runs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_runs_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_runs_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
        sa.UniqueConstraint(
            "conversation_id",
            "client_request_id",
            name="uq_runs_conversation_client_request",
        ),
    )
    op.create_index(
        "ix_runs_conversation_created",
        "runs",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runs_workspace_created", "runs", ["workspace_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_runs_one_active_per_workspace",
        "runs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('starting','running','waiting_approval','cancelling') "
            "AND deleted_at IS NULL"
        ),
    )

    # 第二步：创建运行附属的消息、可重放事件和审批记录。
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(content) > 0", name=op.f("ck_messages_content_not_blank")
        ),
        sa.CheckConstraint(
            "role IN ('user','assistant')", name=op.f("ck_messages_role_visible")
        ),
        sa.CheckConstraint("seq > 0", name=op.f("ck_messages_seq_positive")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_messages_run_id_runs", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint(
            "conversation_id", "seq", name="uq_messages_conversation_seq"
        ),
    )
    op.create_index(
        "ix_messages_conversation_live_seq",
        "messages",
        ["conversation_id", "deleted_at", "seq"],
        unique=False,
    )

    op.create_table(
        "run_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(event) > 0", name=op.f("ck_run_events_event_not_blank")
        ),
        sa.CheckConstraint("seq > 0", name=op.f("ck_run_events_seq_positive")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name="fk_run_events_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "seq", name="pk_run_events"),
    )
    op.create_index(
        "ix_run_events_occurred", "run_events", ["occurred_at"], unique=False
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("action_summary", sa.String(length=1000), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("request_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "length(action_summary) > 0",
            name=op.f("ck_approvals_action_summary_not_blank"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','expired','cancelled')",
            name=op.f("ck_approvals_status_valid"),
        ),
        sa.CheckConstraint(
            "length(tool_name) > 0",
            name=op.f("ck_approvals_tool_name_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name="fk_approvals_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
    )
    op.create_index(
        "uq_approvals_one_pending_per_run",
        "approvals",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    # 第三步：创建工作区记忆及绑定到单次运行的不可变快照。
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name=op.f("ck_memory_entries_content_hash_sha256"),
        ),
        sa.CheckConstraint(
            "length(content) > 0", name=op.f("ck_memory_entries_content_not_blank")
        ),
        sa.CheckConstraint(
            "length(content) <= 2000",
            name=op.f("ck_memory_entries_content_size_valid"),
        ),
        sa.CheckConstraint(
            "kind IN ('preference','fact','decision','note')",
            name=op.f("ck_memory_entries_kind_valid"),
        ),
        sa.CheckConstraint(
            "source IN ('manual','run_result')",
            name=op.f("ck_memory_entries_source_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["runs.id"],
            name="fk_memory_entries_source_run_id_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_memory_entries_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_entries"),
    )
    op.create_index(
        "ix_memory_entries_workspace_enabled",
        "memory_entries",
        ["workspace_id", "deleted_at", "enabled", "pinned", "updated_at"],
        unique=False,
    )
    op.create_index(
        "uq_memory_entries_workspace_hash_live",
        "memory_entries",
        ["workspace_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "run_memories",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("memory_entry_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(content) > 0", name=op.f("ck_run_memories_content_not_blank")
        ),
        sa.CheckConstraint(
            "length(content) <= 2000",
            name=op.f("ck_run_memories_content_size_valid"),
        ),
        sa.CheckConstraint(
            "kind IN ('preference','fact','decision','note')",
            name=op.f("ck_run_memories_kind_valid"),
        ),
        sa.CheckConstraint(
            "position > 0", name=op.f("ck_run_memories_position_positive")
        ),
        sa.ForeignKeyConstraint(
            ["memory_entry_id"],
            ["memory_entries.id"],
            name="fk_run_memories_memory_entry_id_memory_entries",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name="fk_run_memories_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "position", name="pk_run_memories"),
    )


def downgrade() -> None:
    """按外键依赖的逆序删除本次迁移创建的数据库对象。"""

    op.drop_table("run_memories")
    op.drop_index("uq_memory_entries_workspace_hash_live", table_name="memory_entries")
    op.drop_index("ix_memory_entries_workspace_enabled", table_name="memory_entries")
    op.drop_table("memory_entries")
    op.drop_index("uq_approvals_one_pending_per_run", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_run_events_occurred", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("ix_messages_conversation_live_seq", table_name="messages")
    op.drop_table("messages")
    op.drop_index("uq_runs_one_active_per_workspace", table_name="runs")
    op.drop_index("ix_runs_workspace_created", table_name="runs")
    op.drop_index("ix_runs_conversation_created", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_conversations_workspace_live_updated", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("uq_workspaces_path_key_live", table_name="workspaces")
    op.drop_index("ix_workspaces_live_updated", table_name="workspaces")
    op.drop_table("workspaces")
