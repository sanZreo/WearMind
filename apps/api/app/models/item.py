"""衣物模型。

设计取舍：
1. `user_id` 是 `NOT NULL` + 外键，且 `ON DELETE CASCADE` ——
   删除账号必须连带清除衣物（架构文档「数据可删除」要求）。
2. 额外加 `UNIQUE (user_id, id)`：这是为将来的**复合外键**铺路。
   当 `item_images` / `item_attributes` / `outfit_items` 引用衣物时，
   它们可以用 `FOREIGN KEY (user_id, item_id) REFERENCES items (user_id, id)`，
   从而在数据库层面保证「子行与父行属于同一用户」，
   而不是靠应用代码记得加过滤。
3. `category` 用 VARCHAR + CHECK（见 `enums.py` 的理由）。
4. `color` 允许为空：文字描述添加衣物时用户可能不说颜色；
   推荐逻辑必须能容忍缺失，而不是强行编一个默认值。
5. `image_ref` 只存引用（将来形如 `uploads/{user_id}/{uuid}.jpg` 的相对键），
   **不存 URL、不存二进制**。存储方案（本地盘 / 对象存储）留待后续设计。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ItemCategory

if TYPE_CHECKING:
    from app.models.user import User

# 从 Python 枚举生成 CHECK 值列表，保证单一事实来源
_CATEGORY_IN = ", ".join(f"'{value}'" for value in ItemCategory.values())


class Item(Base, TimestampMixin):
    __tablename__ = "items"

    __table_args__ = (
        # 复合外键的落点：保证 (user_id, id) 全局唯一，供子表引用
        # 不写 name，交给 naming_convention 生成 uq_items_user_id_id
        UniqueConstraint("user_id", "id"),
        # 类别必须落在枚举集合内
        CheckConstraint(f"category IN ({_CATEGORY_IN})", name="category_valid"),
        # 名称不允许全空白（'   ' 这种）
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        # "某用户的某类衣物" 是最常见的检索形态
        Index("ix_items_user_id_category", "user_id", "category"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        # 不写 name：交给 naming_convention 生成 fk_items_user_id_users
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    user: Mapped[User] = relationship(back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Item id={self.id} user_id={self.user_id} name={self.name!r}>"
