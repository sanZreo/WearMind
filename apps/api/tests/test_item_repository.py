"""ItemRepository 的隔离测试。

这里验证的是**数据访问层**的隔离：仓储的每一个查询/写入都带 `ctx.user_id`。
它**不等于**系统层面的安全隔离 —— 仓储之上还需要：
真实认证、路由授权、以及"客户端不能指定 user_id"的输入约束（后者已由 schema 的
`extra="forbid"` 保证，见 test_items_api.py）。

与 Phase 1 的 test_data_isolation.py 的区别：
那个文件验证的是"数据库约束能挡住什么"，本文件验证"仓储 API 的形状本身
不允许传入别人的 user_id"。
"""

from __future__ import annotations

import pytest
from app.core.user_context import UserContext
from app.models import Item, ItemCategory
from app.repositories.item_repository import ItemRepository

from tests.factories import make_context, make_user


@pytest.fixture
def two_users(db_session):
    return make_user(db_session, "Alice"), make_user(db_session, "Bob")


@pytest.fixture
def repo_a(db_session, two_users):
    alice, _ = two_users
    return ItemRepository(db_session, make_context(alice))


@pytest.fixture
def repo_b(db_session, two_users):
    _, bob = two_users
    return ItemRepository(db_session, make_context(bob))


# ---------------------------------------------------------------------------
# 构造与 API 形状：从结构上排除"传别人的 user_id"
# ---------------------------------------------------------------------------


def test_constructor_requires_user_context(db_session):
    with pytest.raises(TypeError):
        ItemRepository(db_session, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ItemRepository(db_session, 1)  # type: ignore[arg-type]


def test_create_has_no_user_id_parameter(repo_a):
    """create_item 签名里没有 user_id —— 归属只可能来自上下文。"""
    with pytest.raises(TypeError):
        repo_a.create_item(name="白衬衫", category="top", user_id=999999)  # type: ignore[call-arg]


def test_repository_does_not_expose_session(repo_a):
    assert not hasattr(repo_a, "session")


# ---------------------------------------------------------------------------
# 读：只能看到自己的
# ---------------------------------------------------------------------------


def test_list_returns_only_own_items(repo_a, repo_b):
    repo_a.create_item(name="白衬衫", category=ItemCategory.top.value)
    repo_a.create_item(name="黑西裤", category=ItemCategory.bottom.value)
    repo_b.create_item(name="牛仔裤", category=ItemCategory.bottom.value)

    assert {i.name for i in repo_a.list_items()} == {"白衬衫", "黑西裤"}
    assert {i.name for i in repo_b.list_items()} == {"牛仔裤"}


def test_count_is_scoped_to_user(repo_a, repo_b):
    repo_a.create_item(name="白衬衫", category="top")
    repo_b.create_item(name="牛仔裤", category="bottom")
    repo_b.create_item(name="灰卫衣", category="top")

    assert repo_a.count_items() == 1
    assert repo_b.count_items() == 2


def test_get_own_item(repo_a):
    created = repo_a.create_item(name="白衬衫", category="top")
    found = repo_a.get_item(created.id)
    assert found is not None
    assert found.name == "白衬衫"
    assert found.user_id == repo_a.ctx.user_id


def test_get_other_users_item_returns_none(repo_a, repo_b):
    bob_item = repo_b.create_item(name="牛仔裤", category="bottom")
    assert repo_a.get_item(bob_item.id) is None


def test_get_nonexistent_item_returns_none(repo_a):
    assert repo_a.get_item(999_999_999) is None


def test_list_pagination(repo_a):
    for index in range(5):
        repo_a.create_item(name=f"衣物{index}", category="top")

    page = repo_a.list_items(limit=2, offset=0)
    assert len(page) == 2
    # 排序稳定：最近创建的在前
    assert [i.name for i in page] == ["衣物4", "衣物3"]

    rest = repo_a.list_items(limit=2, offset=2)
    assert [i.name for i in rest] == ["衣物2", "衣物1"]


# ---------------------------------------------------------------------------
# 写：更新/删除只能命中自己的
# ---------------------------------------------------------------------------


def test_update_own_item(repo_a):
    created = repo_a.create_item(name="白衬衫", category="top", color="白色")
    updated = repo_a.update_item(created.id, name="米白衬衫", color="米白")

    assert updated is not None
    assert updated.name == "米白衬衫"
    assert updated.color == "米白"
    # 未提供的字段保持不变
    assert updated.category == "top"


def test_update_can_clear_optional_field(repo_a):
    created = repo_a.create_item(name="白衬衫", category="top", color="白色")
    updated = repo_a.update_item(created.id, color=None)

    assert updated is not None
    assert updated.color is None


def test_empty_update_is_a_noop(repo_a):
    created = repo_a.create_item(name="白衬衫", category="top")
    result = repo_a.update_item(created.id)

    assert result is not None
    assert result.name == "白衬衫"


def test_update_other_users_item_returns_none_and_leaves_it_untouched(repo_a, repo_b, db_session):
    bob_item = repo_b.create_item(name="牛仔裤", category="bottom")

    result = repo_a.update_item(bob_item.id, name="被改名了")

    assert result is None
    db_session.expire_all()
    reloaded = db_session.get(Item, bob_item.id)
    assert reloaded is not None
    assert reloaded.name == "牛仔裤"
    assert reloaded.user_id == repo_b.ctx.user_id


def test_update_nonexistent_item_returns_none(repo_a):
    assert repo_a.update_item(999_999_999, name="不存在") is None


def test_delete_own_item(repo_a, db_session):
    created = repo_a.create_item(name="白衬衫", category="top")
    assert repo_a.delete_item(created.id) is True

    db_session.expire_all()
    assert db_session.get(Item, created.id) is None


def test_delete_other_users_item_returns_false_and_keeps_it(repo_a, repo_b, db_session):
    bob_item = repo_b.create_item(name="牛仔裤", category="bottom")

    assert repo_a.delete_item(bob_item.id) is False

    db_session.expire_all()
    assert db_session.get(Item, bob_item.id) is not None


def test_delete_nonexistent_item_returns_false(repo_a):
    assert repo_a.delete_item(999_999_999) is False


# ---------------------------------------------------------------------------
# 归属
# ---------------------------------------------------------------------------


def test_created_item_belongs_to_context_user(repo_a, repo_b, db_session):
    a_item = repo_a.create_item(name="白衬衫", category="top")
    b_item = repo_b.create_item(name="牛仔裤", category="bottom")

    assert a_item.user_id == repo_a.ctx.user_id
    assert b_item.user_id == repo_b.ctx.user_id
    assert a_item.user_id != b_item.user_id

    db_session.expire_all()
    assert db_session.get(Item, a_item.id).user_id == repo_a.ctx.user_id


def test_created_item_has_server_generated_fields(repo_a):
    created = repo_a.create_item(name="白衬衫", category="top")
    assert isinstance(created.id, int) and created.id > 0
    assert created.created_at is not None
    assert created.updated_at is not None


def test_two_contexts_with_same_session_do_not_leak(db_session, two_users):
    """同一个 Session 上交替使用两个上下文，仍然互不可见。"""
    alice, bob = two_users
    repo_a = ItemRepository(db_session, make_context(alice))
    repo_b = ItemRepository(db_session, make_context(bob))

    repo_a.create_item(name="A 的上衣", category="top")
    repo_b.create_item(name="B 的上衣", category="top")

    assert {i.name for i in repo_a.list_items()} == {"A 的上衣"}
    assert {i.name for i in repo_b.list_items()} == {"B 的上衣"}


def test_context_origin_is_development_identity(db_session, two_users):
    alice, _ = two_users
    ctx = make_context(alice)
    assert isinstance(ctx, UserContext)
    assert ctx.is_development_identity is True
