"""持久化 Web 状态使用的 SQLAlchemy 模型。

这里只保存用户可见的会话文本和经过专门清洗的运行事件。隐藏推理、供应商原始
响应、环境变量和完整工具输出按设计均没有持久化字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import PermissionMode, RunStatus


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
SAFE_JSON = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """所有 SQLAlchemy 声明式模型的公共基类。"""

    # 为约束和索引提供跨数据库一致、便于迁移审查的自动命名规则。
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """为实体提供由数据库维护的创建和更新时间。"""

    # 实体首次插入数据库的时间，由数据库服务器生成。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 实体最近一次更新的时间，由 ORM 更新操作维护。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SoftDeleteMixin:
    """为需要保留审计记录的实体提供软删除时间。"""

    # 软删除发生时间；为 None 表示记录仍然有效。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


