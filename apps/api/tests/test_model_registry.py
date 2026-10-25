"""模型注册表完整性测试。

这类测试不碰数据库，但它守住一个**静默失效**风险：
新增模型文件却忘记在 `app/models/__init__.py` 里 import 时，
Alembic 自动生成会悄无声息地漏掉这张表 —— 没有报错，只是迁移里没有。
"""

from __future__ import annotations

import app.models  # noqa: F401  —— 导入即注册
from app.db.base import Base

EXPECTED_TABLES = {"users", "items"}


def test_all_expected_tables_are_registered():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_mappers_configure_without_error():
    """关系配置有误会在这里抛异常（如 back_populates 拼错）。"""
    from sqlalchemy.orm import configure_mappers

    configure_mappers()


def test_items_has_user_id_not_nullable():
    col = Base.metadata.tables["items"].c.user_id
    assert col.nullable is False
    assert [fk.target_fullname for fk in col.foreign_keys] == ["users.id"]


def test_items_foreign_key_is_cascade():
    col = Base.metadata.tables["items"].c.user_id
    (fk,) = col.foreign_keys
    assert fk.ondelete == "CASCADE"


def test_items_composite_unique_exists():
    """UNIQUE (user_id, id) 是将来复合外键的地基，不能在重构中被删掉。"""
    table = Base.metadata.tables["items"]
    target_cols = {"user_id", "id"}
    assert any(
        {c.name for c in constraint.columns} == target_cols
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )
