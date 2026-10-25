"""应用配置。

设计要点：
1. 全部配置项集中在 Settings 中，禁止在业务代码里散落 os.getenv。
2. Settings.safe_summary() 只输出"是否已配置"，绝不输出密钥内容，
   因此可以安全地打进启动日志。
3. DATABASE_URL 允许为空 —— 空值表示"尚未配置"，而不是"已连接"。
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"


class LogFormat(StrEnum):
    text = "text"
    json = "json"


class LLMProviderName(StrEnum):
    online = "online"
    ollama = "ollama"


class PrivacyMode(StrEnum):
    local_only = "local_only"
    hybrid = "hybrid"
    cloud_ok = "cloud_ok"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用 ----
    app_env: AppEnv = AppEnv.development
    app_name: str = "WearMind"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.text
    cors_origins: str = "http://localhost:3000"

    # ---- 数据库 ----
    # 空字符串 = 尚未配置。绝不设默认 DSN，避免"看起来连上了"。
    database_url: str = ""
    db_echo: bool = False

    # ---- 模型接入 ----
    llm_provider: LLMProviderName = LLMProviderName.online
    online_model_provider: str = ""
    online_model_name: str = ""
    online_model_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"

    # ---- 隐私 ----
    privacy_mode: PrivacyMode = PrivacyMode.hybrid

    # ---- 开发身份（**不是认证**）----
    # 仅当 APP_ENV=development 且 dev_user_enabled=True 时才生效。
    # 生产环境若开启，Settings 会直接拒绝构造（见下方 model_validator），
    # 让"生产环境误用开发身份"变成启动失败，而不是静默放行。
    dev_user_enabled: bool = False
    # 用 UUID 而非自增 ID 作为开发用户标识：不依赖插入顺序，
    # 换机器/重建库后同一个配置仍指向同一个逻辑用户。
    dev_user_public_id: str = ""
    dev_user_display_name: str = "本地开发用户"

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if not value.startswith(("postgresql+psycopg://", "postgresql://")):
            raise ValueError(
                "DATABASE_URL 必须使用 postgresql+psycopg:// 或 postgresql:// 协议；"
                f"当前值以 {value.split(':', 1)[0]}:// 开头"
            )
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = (value or "INFO").upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL 必须是 {sorted(allowed)} 之一")
        return upper

    @field_validator("dev_user_public_id")
    @classmethod
    def _validate_dev_user_public_id(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise ValueError("DEV_USER_PUBLIC_ID 必须是合法 UUID（例如 xxxxxxxx-xxxx-4xxx-...）") from exc

    @model_validator(mode="after")
    def _guard_development_identity(self) -> Settings:
        """把"开发身份被用错环境"变成启动期错误，而不是运行期静默放行。"""
        if self.dev_user_enabled and not self.dev_user_public_id:
            raise ValueError("DEV_USER_ENABLED=true 时必须同时设置 DEV_USER_PUBLIC_ID")

        if self.app_env is AppEnv.production and self.dev_user_enabled:
            raise ValueError(
                "生产环境禁止启用开发身份：请关闭 DEV_USER_ENABLED，"
                "并在接入正式认证后再对外提供服务"
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def online_model_configured(self) -> bool:
        return bool(self.online_model_provider and self.online_model_name and self.online_model_api_key)

    @property
    def development_identity_allowed(self) -> bool:
        """开发身份是否可用。三个条件同时满足才行，缺一即为"无身份"。"""
        return (
            self.app_env is AppEnv.development
            and self.dev_user_enabled
            and bool(self.dev_user_public_id)
        )

    @property
    def auth_mode(self) -> str:
        """当前的身份来源模式，给日志与 /health 用。

        - `development_identity`：开发注入，**不是认证**
        - `unauthenticated`：未接入认证且开发身份不可用 → 需要身份的接口全部 401
        """
        return "development_identity" if self.development_identity_allowed else "unauthenticated"

    def safe_summary(self) -> dict[str, object]:
        """可安全写入日志的配置概览 —— 只暴露布尔与枚举，不暴露密钥。"""
        return {
            "app_env": self.app_env.value,
            "database_configured": self.database_configured,
            "llm_provider": self.llm_provider.value,
            "online_model_configured": self.online_model_configured,
            "online_model_provider": self.online_model_provider or None,
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "privacy_mode": self.privacy_mode.value,
            # 明确写出"当前身份来自开发注入"，避免被误读成已接入认证
            "auth_mode": self.auth_mode,
        }


def get_settings() -> Settings:
    """返回配置单例（uvicorn --reload 下仍能读到最新值，故不做 lru_cache）。"""
    return Settings()
