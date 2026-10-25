"""Pytest 公共配置。

两类测试，环境要求不同：

1. **应用层测试**（`test_health.py` / `test_config.py`）：
   必须在"没有数据库、没有密钥"的干净环境下也能跑通 —— 这是应用应当支持的
   降级状态。因此 `_clean_env` 主动把 `DATABASE_URL` 置空，
   使 `Settings` 走"未配置"分支（环境变量优先级高于 .env 文件）。

2. **数据库集成测试**（`test_data_isolation.py`）：
   需要真实 PostgreSQL。由于上一条把环境变量置空，这里**绕过 Settings，
   直接从 `apps/api/.env` 读取连接串**，二者互不干扰。

数据库测试的隔离策略：**每个测试跑在一个最终被 rollback 的外层事务里**，
因此无论断言成功与否都不会向开发库写入数据。代价是：这些测试依赖
"迁移已执行"这一前提，未执行时会被 skip 而不是 fail（见 `_db_engine`）。

API 测试（`test_items_api.py`）复用同一套隔离：把应用的 `get_db_session`
依赖覆盖为上面这个事务内 Session，因此路由里的 commit 退化为 SAVEPOINT 释放，
外层事务结束时统一 rollback —— 测试**不会**向开发库留下数据。
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

# 确保 apps/api 目录在 sys.path 上，使 `import app` 可用（不依赖安装）
API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ENV_FILE = API_ROOT / ".env"

# 测试用的固定开发用户标识（与 .env.example 中的值一致，但不依赖本机 .env）
TEST_DEV_PUBLIC_ID = "8f3a1c2e-0b7d-4e5f-9a61-2c4d8e7b1f30"


@pytest.fixture(autouse=True, scope="session")
def _clean_env() -> None:
    os.environ["APP_ENV"] = "development"
    os.environ["LOG_LEVEL"] = "WARNING"  # 避免测试输出被访问日志刷屏
    os.environ["DATABASE_URL"] = ""  # 明确表示"未配置"
    os.environ["ONLINE_MODEL_API_KEY"] = ""
    os.environ.pop("OLLAMA_BASE_URL", None)
    # 开发身份默认关闭：需要身份的测试自己用 monkeypatch 打开。
    # 这样"默认不能拿身份"这件事在每个测试里都是显式的。
    os.environ["DEV_USER_ENABLED"] = "false"
    os.environ["DEV_USER_PUBLIC_ID"] = TEST_DEV_PUBLIC_ID
    os.environ["DEV_USER_DISPLAY_NAME"] = "测试开发用户"


@pytest.fixture(scope="session")
def client():
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 数据库集成测试夹具
# ---------------------------------------------------------------------------


def _read_database_url_from_env_file() -> str:
    """只从 .env 读，不经 Settings（避开 _clean_env 的置空）。"""
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL="):
            return stripped.split("=", 1)[1].strip()
    return ""


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _read_database_url_from_env_file()
    if not url:
        pytest.skip("未检测到 apps/api/.env 中的 DATABASE_URL，跳过数据库集成测试")
    return url


@pytest.fixture(scope="session")
def db_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, poolclass=NullPool)

    # 迁移未执行时表不存在 —— 明确 skip，而不是让测试以"表不存在"的错误红掉
    tables = set(inspect(engine).get_table_names())
    missing = {"users", "items"} - tables
    if missing:
        engine.dispose()
        pytest.skip(f"数据库缺少表 {sorted(missing)}，请先执行 `alembic upgrade head`")

    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Session:
    """加入一个外层事务的 Session；测试结束一律 rollback，绝不落库。"""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        # 即使测试内部调用过 commit，这里回滚的是外层事务
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# 用户与上下文的构造辅助（实现见 tests/factories.py）
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """带数据库的 API 客户端。

    关键点：把应用的 `get_db_session` 覆盖为**事务内 Session**，
    路由里的 commit 会退化成 SAVEPOINT 释放，外层事务最终 rollback，
    因此测试不会污染开发库（与既有隔离策略一致）。
    """
    from app.api.deps import get_db_session
    from app.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEV_USER_ENABLED", "true")
    monkeypatch.setenv("DEV_USER_PUBLIC_ID", TEST_DEV_PUBLIC_ID)

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def dev_user(db_session: Session):
    """取（或创建）与 DEV_USER_PUBLIC_ID 对应的开发用户，供断言归属用。

    注意：API 请求里该用户是由 `resolve_user_context` 按需幂等创建的，
    这里用同一个 `public_id` 查找，因此拿到的是**同一条记录**。
    """
    from app.models import User
    from sqlalchemy import select

    from tests.factories import make_user

    public_id = uuid.UUID(TEST_DEV_PUBLIC_ID)
    user = db_session.execute(select(User).where(User.public_id == public_id)).scalar_one_or_none()
    if user is None:
        user = make_user(db_session, "测试开发用户")
        user.public_id = public_id
        db_session.flush()
    return user
