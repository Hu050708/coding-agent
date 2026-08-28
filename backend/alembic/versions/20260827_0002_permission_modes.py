"""将旧权限模式替换为工作区范围的审批模式。

Revision ID: 20260827_0002
Revises: 20260827_0001
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0002"
down_revision: str | None = "20260827_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """移除旧约束、迁移历史值，再应用新的三档权限约束。"""

    # 第一步：暂时移除检查约束，允许把所有历史值原子映射到新语义。
    op.drop_constraint(
        op.f("ck_conversations_permission_mode_valid"),
        "conversations",
        type_="check",
    )
    op.drop_constraint(op.f("ck_runs_permission_mode_valid"), "runs", type_="check")

    op.execute(
        sa.text(
            "UPDATE conversations SET default_permission_mode = CASE "
            "WHEN default_permission_mode = 'review' THEN 'ask' "
            "WHEN default_permission_mode = 'workspace' THEN 'agent' "
            "WHEN default_permission_mode = 'auto' THEN 'workspace_full' "
            "ELSE default_permission_mode END"
        )
    )
    op.execute(
        sa.text(
            "UPDATE runs SET permission_mode = CASE "
            "WHEN permission_mode = 'review' THEN 'ask' "
            "WHEN permission_mode = 'workspace' THEN 'agent' "
            "WHEN permission_mode = 'auto' THEN 'workspace_full' "
            "ELSE permission_mode END"
        )
    )

    # 第二步：数据全部转换完成后再恢复新值域约束。
    op.create_check_constraint(
        op.f("ck_conversations_permission_mode_valid"),
        "conversations",
        "default_permission_mode IN ('ask','agent','workspace_full')",
    )
    op.create_check_constraint(
        op.f("ck_runs_permission_mode_valid"),
        "runs",
        "permission_mode IN ('ask','agent','workspace_full')",
    )


def downgrade() -> None:
    """按相反顺序把新权限模式映射回旧值域。"""

    # 回滚同样先解除约束，完成数据映射后再恢复旧约束。
    op.drop_constraint(
        op.f("ck_conversations_permission_mode_valid"),
        "conversations",
        type_="check",
    )
    op.drop_constraint(op.f("ck_runs_permission_mode_valid"), "runs", type_="check")

    op.execute(
        sa.text(
            "UPDATE conversations SET default_permission_mode = CASE "
            "WHEN default_permission_mode = 'ask' THEN 'review' "
            "WHEN default_permission_mode = 'agent' THEN 'workspace' "
            "WHEN default_permission_mode = 'workspace_full' THEN 'auto' "
            "ELSE default_permission_mode END"
        )
    )
    op.execute(
        sa.text(
            "UPDATE runs SET permission_mode = CASE "
            "WHEN permission_mode = 'ask' THEN 'review' "
            "WHEN permission_mode = 'agent' THEN 'workspace' "
            "WHEN permission_mode = 'workspace_full' THEN 'auto' "
            "ELSE permission_mode END"
        )
    )

    op.create_check_constraint(
        op.f("ck_conversations_permission_mode_valid"),
        "conversations",
        "default_permission_mode IN ('review','workspace','auto')",
    )
    op.create_check_constraint(
        op.f("ck_runs_permission_mode_valid"),
        "runs",
        "permission_mode IN ('review','workspace','auto')",
    )


__all__ = ["downgrade", "upgrade"]
