"""配置模块的单元测试。

重点：密钥绝不能出现在 safe_summary() 中，非法 DSN 必须被拒绝。
"""

from __future__ import annotations

import pytest
from app.core.config import PrivacyMode, Settings
from pydantic import ValidationError


def _settings(**overrides) -> Settings:
    base = {
        "_env_file": None,  # 不读 .env，避免本机环境影响测试
    }
    return Settings(**base, **overrides)


def test_defaults_are_safe():
    s = _settings()
    assert s.database_configured is False
    assert s.online_model_configured is False
    assert s.privacy_mode is PrivacyMode.hybrid


def test_safe_summary_never_contains_key():
    dummy_key = "dummy-value-for-leak-test-only"
    s = _settings(
        online_model_provider="openai",
        online_model_name="gpt-vision-test",
        online_model_api_key=dummy_key,
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
    )
    summary = s.safe_summary()
    rendered = str(summary)

    assert s.online_model_configured is True
    assert dummy_key not in rendered
    assert "p@localhost" not in rendered
    assert "api_key" not in rendered


def test_invalid_database_url_rejected():
    with pytest.raises(ValidationError):
        _settings(database_url="mysql://user:pass@localhost/db")


def test_valid_database_url_accepted():
    s = _settings(database_url="postgresql+psycopg://wearmind:secret@localhost:5432/wearmind")
    assert s.database_configured is True


def test_cors_origins_parsed():
    s = _settings(cors_origins="http://localhost:3000, http://127.0.0.1:3000 ")
    assert s.cors_origin_list == ["http://localhost:3000", "http://127.0.0.1:3000"]
