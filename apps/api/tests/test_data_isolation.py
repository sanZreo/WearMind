"""数据隔离与约束的集成测试。

本文件验证的是**数据库层面**能保证什么、不能保证什么：

✅ 已验证
1. 两个用户可以各自拥有衣物，互不干扰；
2. 按 user_id 过滤的查询只返回该用户的衣物；
3. 每件衣物确实归属其创建者（不会"挂到别人名下"）；
4. 外键有效：不存在的 user_id 会被数据库拒绝；
5. ON DELETE CASCADE 有效：删用户即删其衣物；
6. CHECK 约束有效：非法类别、全空白名称会被拒绝；
7. public_id 由数据库生成且唯一。

❌ 本文件**不能**证明的事（重要）

这些测试里 `user_id` 是由测试代码显式传入的。真实系统里，`user_id` 必须来自
**可信的认证上下文**，绝不能来自请求参数。也就是说：

- 本阶段证明的是"模型关系 + 外键 + 带过滤的查询"是通的；
- 真实 API 层仍需要：从会话/JWT 解析出当前用户 → 所有仓储方法强制注入该 user_id
  → 针对"越权访问他人资源"写专门的授权测试（A 拿 B 的 item_id 请求必须 404/403）。

在认证与仓储层落地之前，**不能**声称系统已具备完整的多用户隔离能力。

隔离策略：每个测试跑在 `db_session` 的外层事务里，结束时统一 rollback，
因此不会向开发库留下任何数据。
"""

from __future__ import annotations

import uuid

import pytest
from app.models import Item, ItemCategory, User
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

# ---------------------------------------------------------------------------
# 辅助函数：模拟"数据访问层"的固定过滤形态
# ---------------------------------------------------------------------------


def _create_user(session, display_name: str) -> User:
    user = User(display_name=display_name)
    session.add(user)
    session.flush()
    return user


def _create_item(
    session,
    user: User,
    name: str,
    category: ItemCategory = ItemCategory.top,
    color: str | None = "白色",
) -> Item:
    item = Item(user_id=user.id, name=name, category=category.value, color=color)
    session.add(item)
    session.flush()
    return item


def _list_items_for(session, user_id: int) -> list[Item]:
    """演示仓储层的正确形态：user_id 是**必填参数**，查询永远带过滤条件。

    注意：这里的 user_id 由调用方传入。生产代码应改为从 UserContext 取值，
    让"忘记加过滤"在类型层面就难以发生。
    """
    stmt = select(Item).where(Item.user_id == user_id).order_by(Item.id)
    return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# 隔离行为
# ---------------------------------------------------------------------------


def test_two_users_can_each_own_items(db_session):
    alice = _create_user(db_session, "Alice")
    bob = _create_user(db_session, "Bob")

    _create_item(db_session, alice, "白衬衫")
    _create_item(db_session, bob, "牛仔裤", category=ItemCategory.bottom, color="蓝色")

    assert len(_list_items_for(db_session, alice.id)) == 1
    assert len(_list_items_for(db_session, bob.id)) == 1


def test_query_for_user_a_returns_only_a_items(db_session):
    alice = _create_user(db_session, "Alice")
    bob = _create_user(db_session, "Bob")

    _create_item(db_session, alice, "白衬衫")
    _create_item(db_session, alice, "灰T恤")
    _create_item(db_session, bob, "牛仔裤", category=ItemCategory.bottom)

    alice_items = _list_items_for(db_session, alice.id)

    assert {item.name for item in alice_items} == {"白衬衫", "灰T恤"}
    assert all(item.user_id == alice.id for item in alice_items)
    assert "牛仔裤" not in {item.name for item in alice_items}


def test_items_keep_their_own_owner(db_session):
    """B 的衣物不会被错误关联给 A。"""
    alice = _create_user(db_session, "Alice")
    bob = _create_user(db_session, "Bob")

    bob_item = _create_item(db_session, bob, "棕色风衣", category=ItemCategory.outerwear)

    assert bob_item.user_id == bob.id
    assert bob_item.user_id != alice.id
    assert bob_item not in _list_items_for(db_session, alice.id)


def test_total_counts_match_owners(db_session):
    """按用户分组计数，确认没有"凭空多出"或无主记录。"""
    alice = _create_user(db_session, "Alice")
    bob = _create_user(db_session, "Bob")

    for _ in range(3):
        _create_item(db_session, alice, "白衬衫")
    _create_item(db_session, bob, "牛仔裤", category=ItemCategory.bottom)

    stmt = select(Item.user_id, func.count()).group_by(Item.user_id)
    counts = dict(db_session.execute(stmt).all())

    assert counts[alice.id] == 3
    assert counts[bob.id] == 1


# ---------------------------------------------------------------------------
# 约束有效性
# ---------------------------------------------------------------------------


def test_foreign_key_rejects_unknown_user(db_session):
    ghost = Item(user_id=999_999_999, name="幽灵衬衫", category=ItemCategory.top.value)

    # 用 SAVEPOINT 包住，失败后外层事务仍可用
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(ghost)
        db_session.flush()


def test_cascade_delete_removes_items(db_session):
    user = _create_user(db_session, "Temp")
    _create_item(db_session, user, "白衬衫")
    _create_item(db_session, user, "黑西裤", category=ItemCategory.bottom)
    user_id = user.id

    db_session.delete(user)
    db_session.flush()
    db_session.expire_all()

    remaining = db_session.execute(
        select(func.count()).select_from(Item).where(Item.user_id == user_id)
    ).scalar_one()
    assert remaining == 0


def test_invalid_category_is_rejected(db_session):
    user = _create_user(db_session, "Alice")
    bad = Item(user_id=user.id, name="不明物体", category="spacesuit")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(bad)
        db_session.flush()


def test_blank_name_is_rejected(db_session):
    user = _create_user(db_session, "Alice")
    blank = Item(user_id=user.id, name="   ", category=ItemCategory.top.value)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(blank)
        db_session.flush()


def test_public_id_is_generated_and_unique(db_session):
    alice = _create_user(db_session, "Alice")
    bob = _create_user(db_session, "Bob")

    db_session.refresh(alice)
    db_session.refresh(bob)

    assert isinstance(alice.public_id, uuid.UUID)
    assert isinstance(bob.public_id, uuid.UUID)
    assert alice.public_id != bob.public_id
