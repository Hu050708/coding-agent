"""显式管理 Web 应用的 SQLAlchemy 引擎和会话生命周期。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConfigurationError(RuntimeError):
    """数据库 URL 或所选驱动不符合应用要求时抛出。"""

    pass


@dataclass(slots=True)
class Database:
    """封装 SQLAlchemy 引擎及其事务会话工厂。"""

    # 负责连接池和数据库连接创建的共享引擎。
    engine: Engine
    # 为每个业务事务创建独立 Session 的工厂。
    session_factory: sessionmaker[Session]

    @contextmanager
    def session(self) -> Iterator[Session]:
        """提供一个事务，并始终关闭其会话。

        :return: 上下文管理器期间可用的 SQLAlchemy 会话。
        :raises BaseException: 业务代码异常会在回滚事务后原样抛出。
        """

        with self.session_factory() as db_session:
            try:
                yield db_session
                db_session.commit()
            except BaseException:
                db_session.rollback()
                raise

    def healthcheck(self) -> None:
        """执行最小查询验证数据库当前是否可连接。"""

        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        """释放引擎连接池持有的所有数据库连接。"""

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

    :param database_url: SQLAlchemy 格式的数据库连接 URL。
    :param require_postgresql: 是否强制使用 PostgreSQL 及 psycopg 驱动。
    :param echo: 是否让 SQLAlchemy 输出 SQL 调试日志。
    :param engine_options: 覆盖或补充默认引擎选项的映射。
    :return: 尚未主动建立连接的引擎与会话工厂封装。
    :raises DatabaseConfigurationError: URL 为空、无法解析或不符合驱动要求。
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
    "Database",
    "DatabaseConfigurationError",
    "create_database",
]
