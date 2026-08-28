"""提供隔离的 PostgreSQL 持久化测试夹具。"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from coding_agent.database import create_database
from coding_agent.models import Base
from coding_agent.repository import PersistenceService


@pytest.fixture()
def persistence(tmp_path):
    database = create_database(
        f"sqlite+pysqlite:///{tmp_path / 'persistence.sqlite3'}",
        require_postgresql=False,
    )
    Base.metadata.create_all(database.engine)
    try:
        yield PersistenceService(database.session_factory), database
    finally:
        database.dispose()
