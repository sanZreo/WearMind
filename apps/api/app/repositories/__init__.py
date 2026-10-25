"""仓储层（数据访问）。

约定：所有仓储方法以 `UserContext` 为边界，不接收裸 `user_id`。
"""

from __future__ import annotations

from app.repositories.item_repository import ItemRepository

__all__ = ["ItemRepository"]
