"""显式管理 Web 应用的 SQLAlchemy 引擎和会话生命周期。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import os
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


DATABASE_URL_ENV = "CODING_AGENT_DATABASE_URL"


class DatabaseConfigurationError(RuntimeError):
    pass


def database_url_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    variable: str = DATABASE_URL_ENV,
) -> str:
    source = os.environ if environ is None else environ
    value = source.get(variable, "").strip()
    if not value:
        raise DatabaseConfigurationError(
            f"{variable} is required for the web application PostgreSQL store."
        )
    return value


@dataclass(slots=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    @contextmanager
    def session(self) -> Iterator[Session]:
        """提供一个事务，并始终关闭其会话。"""

        with self.session_factory() as db_session:
            try:
                yield db_session
                db_session.commit()
            except BaseException:
                db_session.rollback()
                raise

    def healthcheck(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        self.engine.dispose()


def create_database(
    database_url: str,
    *,
    require_postgresql: bool = True,
    echo: bool = False,
    engine_options: Mapping[str, Any] | None = None,
) -> Database:
    """创建尚未连接的数据库引擎和事务工厂。

    生产调用方保持 ``require_postgresql=True``。单元测试可显式传入 SQLite URL 和
    ``False``，确保 PostgreSQL 不可用时 Web 服务绝不会静默降级。
    """

    # 第一步：解析 URL，并按调用场景显式要求 PostgreSQL 及 psycopg 驱动。
    if not isinstance(database_url, str) or not database_url.strip():
        raise DatabaseConfigurationError("database URL must be non-empty")
    try:
        parsed = make_url(database_url.strip())
    except Exception as exc:  # SQLAlchemy 会针对不同解析失败抛出多种异常。
        raise DatabaseConfigurationError("database URL is invalid") from exc
    if require_postgresql and parsed.get_backend_name() != "postgresql":
        raise DatabaseConfigurationError("the web application requires PostgreSQL")
    if require_postgresql and parsed.drivername != "postgresql+psycopg":
        raise DatabaseConfigurationError(
            "CODING_AGENT_DATABASE_URL must use the postgresql+psycopg driver"
        )

    # 第二步：应用安全默认引擎参数，构建短生命周期事务会话工厂。
    options: dict[str, Any] = {
        "echo": echo,
        "future": True,
        "hide_parameters": True,
        "pool_pre_ping": True,
    }
    options.update(dict(engine_options or {}))
    engine = create_engine(parsed, **options)
    factory = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    return Database(engine=engine, session_factory=factory)


__all__ = [
    "DATABASE_URL_ENV",
    "Database",
    "DatabaseConfigurationError",
    "create_database",
    "database_url_from_environment",
]
