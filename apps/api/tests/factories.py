"""测试数据构造辅助。

放在独立模块而不是 conftest，是因为 `tests/` 是一个包（有 `__init__.py`），
测试模块以 `tests.xxx` 形式导入；辅助函数需要能被多个测试文件共享，
且不希望它们被 pytest 当成 fixtures 收集。
"""

from __future__ import annotations

from app.core.user_context import UserContext, UserOrigin
from app.models import User
from sqlalchemy.orm import Session


def make_user(session: Session, display_name: str) -> User:
    """建一个用户，并确保 server_default 生成的 public_id 已回填。"""
    user = User(display_name=display_name)
    session.add(user)
    session.flush()
    if user.public_id is None:  # pragma: no cover - 正常由 RETURNING 回填
        session.refresh(user)
    return user


def make_context(user: User, origin: UserOrigin = UserOrigin.development_identity) -> UserContext:
    """由 User 构造 UserContext —— 测试里唯一的构造入口。"""
    return UserContext(user_id=user.id, public_id=user.public_id, origin=origin)
