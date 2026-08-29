"""供 FastAPI 生命周期启动阶段调用的 Alembic 编程入口。"""

from __future__ import annotations

from pathlib import Path


class DatabaseMigrationError(RuntimeError):
    """数据库迁移配置或执行失败时抛出。"""

    pass


def default_alembic_config_path() -> Path:
    """定位后端目录中的默认 Alembic 配置文件。

    :return: ``backend/alembic.ini`` 的绝对路径。
    """

    return Path(__file__).resolve().parents[3] / "alembic.ini"


def upgrade_database(database_url: str, *, config_path: str | Path | None = None) -> None:
    """将配置的数据库升级到 ``head``，且不记录其 DSN。

    :param database_url: 迁移目标数据库的 SQLAlchemy URL。
    :param config_path: 自定义 Alembic 配置路径；为 None 时使用后端默认配置。
    :raises DatabaseMigrationError: URL 为空、配置加载失败或迁移执行失败。
    """

    if not isinstance(database_url, str) or not database_url.strip():
        raise DatabaseMigrationError("database migration URL is required")
    try:
        from alembic import command
        from alembic.config import Config

        path = Path(config_path) if config_path is not None else default_alembic_config_path()
        config = Config(str(path.resolve()))
        # env.py 会优先读取该值而非 ini 配置；Alembic 配置对象仅保留在进程内，
        # 该值不会被打印。
        config.attributes["database_url"] = database_url.strip()
        command.upgrade(config, "head")
    except DatabaseMigrationError:
        raise
    except Exception:
        # 主动截断驱动异常链，因为连接错误中可能包含带凭据的 DSN。
        raise DatabaseMigrationError("database migration failed") from None


__all__ = ["DatabaseMigrationError", "default_alembic_config_path", "upgrade_database"]
