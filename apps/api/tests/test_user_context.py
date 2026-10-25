"""UserContext 与开发身份注入的测试。

覆盖两类风险：

1. **上下文本体**：不可变、参数非法时立即失败（而不是带着脏值往下走）。
2. **身份来源**：只有"开发环境 + 显式开启"才给身份；其它环境一律 401；
   客户端无法通过请求体/查询参数/请求头改变身份。

> ⚠️ 这里验证的是"开发身份注入按设计工作"，**不是**"认证已完成"。
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from app.core.config import Settings
from app.core.user_context import UserContext, UserOrigin
from pydantic import ValidationError

DEV_UUID = uuid.UUID("8f3a1c2e-0b7d-4e5f-9a61-2c4d8e7b1f30")


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


# ---------------------------------------------------------------------------
# UserContext 本体
# ---------------------------------------------------------------------------


def test_context_is_immutable():
    ctx = UserContext(user_id=1, public_id=DEV_UUID)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.user_id = 2  # type: ignore[misc]


def test_context_defaults_to_development_origin():
    ctx = UserContext(user_id=1, public_id=DEV_UUID)
    assert ctx.origin is UserOrigin.development_identity
    assert ctx.is_development_identity is True


@pytest.mark.parametrize("bad_user_id", [0, -1])
def test_context_rejects_non_positive_user_id(bad_user_id):
    with pytest.raises(ValueError):
        UserContext(user_id=bad_user_id, public_id=DEV_UUID)


def test_context_rejects_non_uuid_public_id():
    with pytest.raises(TypeError):
        UserContext(user_id=1, public_id="not-a-uuid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 配置层：开发身份只能出现在开发环境
# ---------------------------------------------------------------------------


def test_dev_identity_off_by_default():
    s = _settings()
    assert s.dev_user_enabled is False
    assert s.development_identity_allowed is False
    assert s.auth_mode == "unauthenticated"


def test_dev_identity_allowed_only_in_development():
    s = _settings(
        app_env="development",
        dev_user_enabled=True,
        dev_user_public_id=str(DEV_UUID),
    )
    assert s.development_identity_allowed is True
    assert s.auth_mode == "development_identity"


def test_staging_does_not_get_development_identity():
    """staging 即使开了开关也不给身份 —— 只有 development 才允许。"""
    s = _settings(
        app_env="staging",
        dev_user_enabled=True,
        dev_user_public_id=str(DEV_UUID),
    )
    assert s.development_identity_allowed is False
    assert s.auth_mode == "unauthenticated"


def test_production_cannot_enable_development_identity():
    """生产环境开启开发身份 → 配置直接拒绝（启动即失败，而不是静默放行）。"""
    with pytest.raises(ValidationError) as excinfo:
        _settings(
            app_env="production",
            dev_user_enabled=True,
            dev_user_public_id=str(DEV_UUID),
        )
    assert "生产环境禁止启用开发身份" in str(excinfo.value)


def test_enabled_without_public_id_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        _settings(app_env="development", dev_user_enabled=True, dev_user_public_id="")
    assert "DEV_USER_PUBLIC_ID" in str(excinfo.value)


def test_invalid_public_id_is_rejected():
    with pytest.raises(ValidationError):
        _settings(
            app_env="development",
            dev_user_enabled=True,
            dev_user_public_id="not-a-uuid",
        )


def test_safe_summary_reports_auth_mode_without_secrets():
    s = _settings(
        app_env="development",
        dev_user_enabled=True,
        dev_user_public_id=str(DEV_UUID),
    )
    summary = s.safe_summary()
    assert summary["auth_mode"] == "development_identity"
    # 开发用户标识本身也不应出现在日志概览里
    assert str(DEV_UUID) not in str(summary)


# ---------------------------------------------------------------------------
# 请求层：身份如何被使用、如何被拒绝
# ---------------------------------------------------------------------------


def test_request_in_development_gets_development_identity(api_client):
    identity = api_client.get("/health").json()["identity"]
    assert identity["auth_mode"] == "development_identity"
    assert identity["development_identity_allowed"] is True


def test_development_user_is_created_once(db_session, monkeypatch):
    """重复解析不会造出第二个开发用户（幂等性由唯一约束保证）。"""
    from app.models import User
    from app.services.identity import resolve_user_context
    from sqlalchemy import func, select

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEV_USER_ENABLED", "true")
    monkeypatch.setenv("DEV_USER_PUBLIC_ID", str(DEV_UUID))

    first = resolve_user_context(db_session)
    second = resolve_user_context(db_session)

    assert first.user_id == second.user_id
    assert first.public_id == DEV_UUID

    count = db_session.execute(
        select(func.count()).select_from(User).where(User.public_id == DEV_UUID)
    ).scalar_one()
    assert count == 1


def test_production_request_is_rejected(api_client, monkeypatch):
    """非开发环境 + 无正式认证 → 401，绝不回退到开发身份。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEV_USER_ENABLED", "false")

    resp = api_client.get("/api/v1/items")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_required"


def test_staging_request_is_rejected_even_with_flag_on(api_client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DEV_USER_ENABLED", "true")

    resp = api_client.post("/api/v1/items", json={"name": "白衬衫", "category": "top"})
    assert resp.status_code == 401


def test_query_param_cannot_change_identity(api_client):
    """查询参数里的 user_id 只是被忽略的噪声，不参与身份判定。"""
    api_client.post("/api/v1/items", json={"name": "我的衬衫", "category": "top"})

    resp = api_client.get("/api/v1/items", params={"user_id": 999999})
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()["items"]}
    assert names == {"我的衬衫"}


def test_header_cannot_change_identity(api_client):
    api_client.post("/api/v1/items", json={"name": "我的衬衫", "category": "top"})

    resp = api_client.get(
        "/api/v1/items",
        headers={"X-User-Id": "999999", "X-User": "999999"},
    )
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()["items"]}
    assert names == {"我的衬衫"}
