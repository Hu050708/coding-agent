"""验证数据库配置解析和连接生命周期。"""

from __future__ import annotations

import pytest

from coding_agent.database import (
    DatabaseConfigurationError,
    create_database,
    database_url_from_environment,
)


def test_database_url_is_required_without_a_fallback() -> None:
    with pytest.raises(DatabaseConfigurationError, match="required"):
        database_url_from_environment({})


def test_production_factory_rejects_sqlite() -> None:
    with pytest.raises(DatabaseConfigurationError, match="requires PostgreSQL"):
        create_database("sqlite+pysqlite:///:memory:")


def test_production_factory_requires_psycopg_driver() -> None:
    with pytest.raises(DatabaseConfigurationError, match=r"postgresql\+psycopg"):
        create_database("postgresql://coding_agent:secret@localhost/coding_agent")


def test_healthcheck_uses_explicit_test_database() -> None:
    database = create_database("sqlite+pysqlite:///:memory:", require_postgresql=False)
    try:
        database.healthcheck()
    finally:
        database.dispose()
