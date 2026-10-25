"""业务枚举。

为什么用「VARCHAR + CHECK 约束 + Python StrEnum」而不是 PostgreSQL 原生 ENUM：

| 方案 | 优点 | 缺点 |
|---|---|---|
| 原生 ENUM | 类型安全最强 | 增删枚举值要 `ALTER TYPE`，Alembic **不会**自动生成；回滚困难；改一次疼一次 |
| VARCHAR + CHECK | 迁移只需改 CHECK 约束；Alembic 可正常表达；值集合单一事实来源在 Python | 需要约束才能保证值合法 |

衣物类别是最可能演化的字段（后续要加「内衣」「运动」等），
因此选择可演化方案，同时用 CHECK 保证数据库层面不会写入非法值。
"""

from __future__ import annotations

from enum import StrEnum


class ItemCategory(StrEnum):
    """衣物类别（第一版）。

    刻意不细分到「T恤/衬衫/卫衣」这一层 —— 那是 `item_attributes` 与标签系统的职责，
    第一版只需要能支撑「上装/下装/外套/连衣裙/鞋/配饰/其他」的搭配逻辑。
    """

    top = "top"
    bottom = "bottom"
    outerwear = "outerwear"
    dress = "dress"
    shoes = "shoes"
    accessory = "accessory"
    other = "other"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)
