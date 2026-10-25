"""身份解析（当前仅开发身份，**不是认证**）。

职责：把"当前请求是谁"解析成 `UserContext`。这是未来接入正式认证时
**唯一**需要替换的地方 —— API 层与仓储层都只依赖 `UserContext`，
不关心它是从哪来的。

安全边界（务必读）：

1. 身份只来自 **服务端配置**（`DEV_USER_ENABLED` + `DEV_USER_PUBLIC_ID`），
   不接受请求体、查询参数或普通请求头里的任何用户标识。
2. 只有 `APP_ENV=development` 才可能命中开发身份；其它环境一律
   `AuthenticationRequired`（401），**不会**退化成某个默认用户。
3. 开发用户的创建是受控且幂等的：靠 `users.public_id` 唯一约束 +
   `ON CONFLICT DO NOTHING` 保证并发下也只会有一条，不会每次请求建一个新用户。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, AuthenticationRequired
from app.core.user_context import UserContext, UserOrigin
from app.models.user import User

logger = logging.getLogger(__name__)


class DevelopmentUserResolutionError(AppError):
    """开发用户无法解析（通常是数据被手工删除/回滚造成）。"""

    status_code = 500
    code = "development_user_unavailable"
    message = (
        "开发用户初始化失败。请检查 DEV_USER_PUBLIC_ID 配置，"
        "或执行 scripts/db_bootstrap.py 确认数据库状态"
    )


def resolve_user_context(session: Session) -> UserContext:
    """解析当前请求的用户上下文。

    正式认证接入前，这里只有一条合法路径：开发环境 + 显式开启的开发身份。
    """
    settings = get_settings()

    if not settings.development_identity_allowed:
        # 明确拒绝，而不是"没人登录就当成某个用户"
        raise AuthenticationRequired()

    user = ensure_development_user(
        session,
        public_id=uuid.UUID(settings.dev_user_public_id),
        display_name=settings.dev_user_display_name,
    )
    return UserContext(
        user_id=user.id,
        public_id=user.public_id,
        origin=UserOrigin.development_identity,
    )


def ensure_development_user(session: Session, *, public_id: uuid.UUID, display_name: str) -> User:
    """按 `public_id` 取开发用户，不存在则受控创建一次。

    幂等性由数据库唯一约束保证：并发请求可能同时走到 INSERT，
    但 `ON CONFLICT DO NOTHING` 让第二个静默失败，随后 SELECT 到同一条记录。
    """
    existing = _find_by_public_id(session, public_id)
    if existing is not None:
        return existing

    stmt = (
        pg_insert(User)
        .values(public_id=public_id, display_name=display_name)
        .on_conflict_do_nothing(index_elements=[User.public_id])
    )
    try:
        session.execute(stmt)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("开发用户创建失败（public_id=%s）", public_id)
        raise

    user = _find_by_public_id(session, public_id)
    if user is None:  # pragma: no cover - 唯一约束下不应出现
        raise DevelopmentUserResolutionError()

    # 用 WARNING 而不是 INFO：这是"身份被凭空创建"，日志里必须显眼
    logger.warning(
        "已创建本地开发用户 public_id=%s（仅开发环境；这不是注册流程，也不代表已接入认证）",
        public_id,
    )
    return user


def _find_by_public_id(session: Session, public_id: uuid.UUID) -> User | None:
    return session.execute(select(User).where(User.public_id == public_id)).scalar_one_or_none()


def identity_debug_info(settings: Settings | None = None) -> dict[str, object]:
    """可安全暴露的身份诊断信息（不含任何用户标识的真实值）。"""
    settings = settings or get_settings()
    return {
        "auth_mode": settings.auth_mode,
        "development_identity_allowed": settings.development_identity_allowed,
        "dev_user_configured": bool(settings.dev_user_public_id),
        "dev_user_enabled": settings.dev_user_enabled,
    }
