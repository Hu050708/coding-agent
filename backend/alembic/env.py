"""配置 Alembic 的离线 SQL 生成和在线数据库迁移。"""

from __future__ import annotations

from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from coding_agent.models import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    value = config.attributes.get("database_url")
    if not value:
        value = os.environ.get("CODING_AGENT_DATABASE_URL", "")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("CODING_AGENT_DATABASE_URL is required for migrations")
    return value.strip()


def run_migrations_offline() -> None:
    """在不建立连接的情况下配置迁移上下文并生成 SQL。"""

    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """建立数据库连接，并在事务中执行实际迁移。"""

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        hide_parameters=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=False,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
