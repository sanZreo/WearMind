"""用户模型。

⚠️ 本阶段的 `users` 表**不代表已有认证机制**。
它只是一个数据模型：用于建立 `items` 的外键归属、以及数据隔离测试。
没有任何登录、会话、密码、令牌字段 —— 因为这些尚未设计，不应先造出半成品。

真实 API 接入后，当前用户必须从**可信认证上下文**（如签名会话 / JWT 校验结果）中获取，
**绝不能接受客户端传入的 user_id**。详见 `docs/design/phase1-users-items.md`。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Identity, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.item import Item


class User(Base, TimestampMixin):
    __tablename__ = "users"

    # 内部主键：BIGINT 自增。用整数而非 UUID 做 PK，
    # 是为了让外键体积更小、B-tree 更紧凑（items 可能很快到万级）。
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)

    # 对外标识：UUID。API 层只暴露 public_id，避免暴露自增 ID
    # （自增 ID 会泄露用户总量与注册顺序，且便于枚举）。
    public_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        server_default=text("gen_random_uuid()"),
        unique=True,
        index=True,
    )

    # 展示名。允许为空 —— 认证尚未实现，注册流程会补上；
    # 现在留空比编造一个假字段更诚实。
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    items: Mapped[list[Item]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,  # 依赖数据库 ON DELETE CASCADE，不先 SELECT 再逐条删
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<User id={self.id} public_id={self.public_id}>"
