"""ORM 基类与元数据约定。

设计要点：
1. 所有模型继承 `Base`（SQLAlchemy 2.x 的 `DeclarativeBase`），共享同一份 `MetaData`。
2. `naming_convention` 让约束名可预测 —— 否则 PostgreSQL 自动生成的约束名
   在 Alembic 里无法稳定引用，回滚时会失败。
3. `TimestampMixin` 统一 `created_at / updated_at`，避免各表各写一套。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 约束命名约定：`%(constraint_name)s` 要求显式命名 CheckConstraint
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """创建/更新时间。

    - `server_default=func.now()`：由数据库生成，绕过应用时钟不一致问题。
    - `onupdate=func.now()`：**由 SQLAlchemy 在 UPDATE 语句里写入**，
      不是数据库触发器。若将来有绕过 ORM 的写入（如批量 SQL），
      `updated_at` 不会自动更新 —— 这是已知取舍，需要时再加触发器。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
