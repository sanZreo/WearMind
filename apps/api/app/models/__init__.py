"""模型注册中心 —— **唯一**的模型导入入口。

为什么必须集中管理：
Alembic 的 `target_metadata` 只包含「已经被 import 过的」模型类。
如果某个模型文件从未被导入，自动生成的迁移会**静默漏掉这张表**，
而且不会有任何报错。因此：

- 新增模型 → 必须在下面 import 一次；
- `migrations/env.py` 只 import 本模块，不逐个 import 模型文件；
- 单测 `test_model_registry.py` 会断言注册表里包含全部预期表名，
  防止「加了模型但忘了注册」这一类静默失效。
"""

from __future__ import annotations

from app.db.base import Base, TimestampMixin
from app.models.enums import ItemCategory
from app.models.item import Item
from app.models.user import User

__all__ = [
    "Base",
    "Item",
    "ItemCategory",
    "TimestampMixin",
    "User",
]
