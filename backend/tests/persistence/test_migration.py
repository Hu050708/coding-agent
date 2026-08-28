"""验证 Alembic 配置定位和迁移错误映射。"""

from __future__ import annotations

from io import StringIO

from alembic import command
from alembic.config import Config

from coding_agent.database.migrations import default_alembic_config_path


def test_initial_migration_compiles_for_postgresql_without_connecting() -> None:
    output = StringIO()
    config = Config(str(default_alembic_config_path()), output_buffer=output)
    config.attributes["database_url"] = (
        "postgresql+psycopg://coding_agent:placeholder@127.0.0.1:5434/coding_agent"
    )
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()

    for table in (
        "workspaces",
        "conversations",
        "runs",
        "messages",
        "run_events",
        "approvals",
        "memory_entries",
        "run_memories",
    ):
        assert f"CREATE TABLE {table}" in sql
    assert "CREATE UNIQUE INDEX uq_runs_one_active_per_workspace" in sql
    assert "WHERE status IN ('starting','running','waiting_approval','cancelling')" in sql
    assert "pgvector" not in sql.casefold()


def test_default_config_path_is_stable_from_the_package() -> None:
    path = default_alembic_config_path()
    assert path.name == "alembic.ini"
    assert path.is_file()
