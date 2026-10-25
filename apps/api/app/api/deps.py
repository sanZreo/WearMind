"""FastAPI 依赖注入。

三层边界，替换正式认证时只需替换 `get_user_context`：

    路由  →  依赖（本文件）  →  仓储（ItemRepository）
              ↓
         UserContext

路由拿不到 `Session`，也拿不到 `user_id`，只能通过仓储间接访问数据。
依赖统一用 `Annotated[...]` 声明，既符合 FastAPI 官方推荐写法，
也让静态检查（B008：默认参数里不要调用函数）保持严格。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DatabaseUnavailable
from app.core.user_context import UserContext
from app.db.session import get_session_factory
from app.repositories.item_repository import ItemRepository
from app.services.identity import resolve_user_context


def get_db_session() -> Iterator[Session]:
    """请求级数据库会话。

    只负责"打开/关闭"，不负责提交 —— 提交由仓储层在自己的写操作里完成。
    路由不直接依赖它（只依赖仓储），避免业务代码拿到 Session 后绕过隔离。
    """
    settings = get_settings()
    if not settings.database_configured:
        raise DatabaseUnavailable("数据库未配置（DATABASE_URL 为空）")

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_db_session)]


def get_user_context(session: SessionDep) -> UserContext:
    """解析当前用户身份。

    ⚠️ 开发阶段实现：只在 `APP_ENV=development` 且开启 `DEV_USER_ENABLED` 时生效。
    正式认证接入后，把这个函数换成"校验会话/JWT → 构造 UserContext"即可，
    仓储层与路由都无需改动。
    """
    return resolve_user_context(session)


UserContextDep = Annotated[UserContext, Depends(get_user_context)]


def get_item_repository(session: SessionDep, ctx: UserContextDep) -> ItemRepository:
    """构造一个已绑定当前用户的衣物仓储。"""
    return ItemRepository(session, ctx)


ItemRepositoryDep = Annotated[ItemRepository, Depends(get_item_repository)]
