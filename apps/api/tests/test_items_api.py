"""衣物 CRUD API 的测试。

重点不在"能增删改查"，而在四条边界：

1. 归属由服务端身份决定，请求体里塞 `user_id` 会被 422 拒绝；
2. 访问他人衣物与访问不存在的衣物**返回完全相同的 404**；
3. 非开发环境没有身份时一律 401；
4. 错误响应不含数据库细节（SQL / DSN / 堆栈）。
"""

from __future__ import annotations

import pytest

from tests.factories import make_user

BASE = "/api/v1/items"


@pytest.fixture
def other_user_item(db_session):
    """属于另一个用户的衣物，用于越权测试。"""
    from app.models import Item

    bob = make_user(db_session, "Bob")
    item = Item(user_id=bob.id, name="Bob 的牛仔裤", category="bottom", color="蓝色")
    db_session.add(item)
    db_session.flush()
    return item


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------


def test_create_item_returns_201(api_client):
    resp = api_client.post(BASE, json={"name": "白衬衫", "category": "top", "color": "白色"})
    assert resp.status_code == 201

    body = resp.json()
    assert body["name"] == "白衬衫"
    assert body["category"] == "top"
    assert body["color"] == "白色"
    assert isinstance(body["id"], int)
    assert body["created_at"] and body["updated_at"]
    # 响应不暴露归属字段
    assert "user_id" not in body


def test_create_trims_name(api_client):
    resp = api_client.post(BASE, json={"name": "  白衬衫  ", "category": "top"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "白衬衫"


def test_create_without_optional_fields(api_client):
    resp = api_client.post(BASE, json={"name": "白衬衫", "category": "top"})
    assert resp.status_code == 201
    assert resp.json()["color"] is None
    assert resp.json()["image_ref"] is None


def test_list_returns_only_own_items(api_client, other_user_item):
    api_client.post(BASE, json={"name": "我的衬衫", "category": "top"})

    resp = api_client.get(BASE)
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 1
    assert [i["name"] for i in body["items"]] == ["我的衬衫"]
    assert "Bob 的牛仔裤" not in {i["name"] for i in body["items"]}


def test_get_own_item(api_client):
    created = api_client.post(BASE, json={"name": "白衬衫", "category": "top"}).json()

    resp = api_client.get(f"{BASE}/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_update_own_item_partially(api_client):
    created = api_client.post(BASE, json={"name": "白衬衫", "category": "top", "color": "白色"}).json()

    resp = api_client.patch(f"{BASE}/{created['id']}", json={"color": "米白"})
    assert resp.status_code == 200

    body = resp.json()
    assert body["color"] == "米白"
    assert body["name"] == "白衬衫"  # 未提供的字段不变
    assert body["category"] == "top"


def test_update_can_clear_color(api_client):
    created = api_client.post(BASE, json={"name": "白衬衫", "category": "top", "color": "白色"}).json()

    resp = api_client.patch(f"{BASE}/{created['id']}", json={"color": None})
    assert resp.status_code == 200
    assert resp.json()["color"] is None


def test_delete_own_item_returns_204(api_client):
    created = api_client.post(BASE, json={"name": "白衬衫", "category": "top"}).json()

    resp = api_client.delete(f"{BASE}/{created['id']}")
    assert resp.status_code == 204
    assert resp.content == b""

    assert api_client.get(f"{BASE}/{created['id']}").status_code == 404


# ---------------------------------------------------------------------------
# 越权：与他人资源不可区分
# ---------------------------------------------------------------------------


def test_get_other_users_item_is_404(api_client, other_user_item):
    resp = api_client.get(f"{BASE}/{other_user_item.id}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "item_not_found"


def test_update_other_users_item_is_404(api_client, other_user_item, db_session):
    resp = api_client.patch(f"{BASE}/{other_user_item.id}", json={"name": "被改名了"})
    assert resp.status_code == 404

    db_session.expire_all()
    from app.models import Item

    assert db_session.get(Item, other_user_item.id).name == "Bob 的牛仔裤"


def test_delete_other_users_item_is_404(api_client, other_user_item, db_session):
    resp = api_client.delete(f"{BASE}/{other_user_item.id}")
    assert resp.status_code == 404

    db_session.expire_all()
    from app.models import Item

    assert db_session.get(Item, other_user_item.id) is not None


def test_other_users_item_is_not_in_list(api_client, other_user_item):
    body = api_client.get(BASE).json()
    assert body["total"] == 0
    assert body["items"] == []


def test_missing_item_404_is_indistinguishable_from_forbidden(api_client, other_user_item):
    """他人资源与不存在的资源，响应体必须逐字节一致（除 request_id 外）。"""
    not_mine = api_client.get(f"{BASE}/{other_user_item.id}")
    missing = api_client.get(f"{BASE}/999999999")

    assert not_mine.status_code == missing.status_code == 404

    def normalize(payload: dict) -> dict:
        payload = dict(payload)
        payload["error"] = dict(payload["error"])
        payload["error"].pop("request_id", None)
        return payload

    assert normalize(not_mine.json()) == normalize(missing.json())


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_category", ["spacesuit", "", "TOP", "上装"])
def test_invalid_category_rejected(api_client, bad_category):
    resp = api_client.post(BASE, json={"name": "白衬衫", "category": bad_category})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("blank_name", ["", "   ", "\t\n"])
def test_blank_name_rejected(api_client, blank_name):
    resp = api_client.post(BASE, json={"name": blank_name, "category": "top"})
    assert resp.status_code == 422


def test_name_too_long_rejected(api_client):
    resp = api_client.post(BASE, json={"name": "衬" * 121, "category": "top"})
    assert resp.status_code == 422


def test_create_rejects_user_id_in_body(api_client, db_session):
    """请求体里的 user_id 不是"被忽略"，而是直接 422 —— 连尝试的入口都没有。"""
    resp = api_client.post(
        BASE,
        json={"name": "白衬衫", "category": "top", "user_id": 999999},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"

    # 确认没有任何记录被创建
    from app.models import Item
    from sqlalchemy import func, select

    assert db_session.execute(select(func.count()).select_from(Item)).scalar_one() == 0


@pytest.mark.parametrize("forbidden_field", ["id", "public_id", "created_at", "updated_at"])
def test_create_rejects_server_owned_fields(api_client, forbidden_field):
    resp = api_client.post(
        BASE,
        json={"name": "白衬衫", "category": "top", forbidden_field: 1},
    )
    assert resp.status_code == 422


def test_patch_rejects_user_id_in_body(api_client):
    created = api_client.post(BASE, json={"name": "白衬衫", "category": "top"}).json()
    resp = api_client.patch(f"{BASE}/{created['id']}", json={"user_id": 999999})
    assert resp.status_code == 422


def test_patch_rejects_explicit_null_name(api_client):
    created = api_client.post(BASE, json={"name": "白衬衫", "category": "top"}).json()
    resp = api_client.patch(f"{BASE}/{created['id']}", json={"name": None})
    assert resp.status_code == 422


def test_patch_empty_body_is_noop(api_client):
    created = api_client.post(BASE, json={"name": "白衬衫", "category": "top"}).json()
    resp = api_client.patch(f"{BASE}/{created['id']}", json={})
    assert resp.status_code == 200
    assert resp.json()["name"] == "白衬衫"


@pytest.mark.parametrize("bad_limit", [0, -1, 101])
def test_list_limit_bounds(api_client, bad_limit):
    assert api_client.get(BASE, params={"limit": bad_limit}).status_code == 422


def test_list_pagination_params(api_client):
    for index in range(3):
        api_client.post(BASE, json={"name": f"衣物{index}", "category": "top"})

    body = api_client.get(BASE, params={"limit": 2, "offset": 0}).json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


# ---------------------------------------------------------------------------
# 身份缺失与错误响应卫生
# ---------------------------------------------------------------------------


def test_no_identity_in_production(api_client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEV_USER_ENABLED", "false")

    assert api_client.get(BASE).status_code == 401
    assert api_client.post(BASE, json={"name": "白衬衫", "category": "top"}).status_code == 401


def test_error_responses_do_not_leak_database_details(api_client, other_user_item):
    bodies = [
        api_client.get(f"{BASE}/{other_user_item.id}").text,
        api_client.post(BASE, json={"name": "", "category": "spacesuit"}).text,
        api_client.get(f"{BASE}/999999999").text,
    ]
    forbidden = (
        "postgresql",
        "psycopg",
        "sqlalchemy",
        "Traceback",
        "SELECT",
        "items.user_id",
        "password",
    )
    for body in bodies:
        lowered = body.lower()
        for token in forbidden:
            assert token.lower() not in lowered, f"响应泄露了 {token}: {body}"


def test_delete_twice_is_404(api_client):
    created = api_client.post(BASE, json={"name": "白衬衫", "category": "top"}).json()
    assert api_client.delete(f"{BASE}/{created['id']}").status_code == 204
    assert api_client.delete(f"{BASE}/{created['id']}").status_code == 404
