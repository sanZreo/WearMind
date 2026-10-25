"""数据库连接模块。

职责：
1. 提供惰性创建的 Engine（导入本模块不会产生任何网络连接）；
2. 提供 check_database() 用于健康检查，如实返回未配置 / 连不上 / 已连接；
3. 提供 get_session_factory() 供数据访问层使用。

注意：本模块存在 ≠ 数据库已验证。是否真正连通以 check_database() 的返回为准。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

DatabaseState = Literal["not_configured", "connected", "unreachable"]

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


@dataclass(frozen=True)
class DatabaseStatus:
    state: DatabaseState
    detail: str
    latency_ms: float | None = None

    @property
    def connected(self) -> bool:
        return self.state == "connected"


def get_engine() -> Engine:
    """惰性创建 Engine。未配置 DATABASE_URL 时直接报错，避免静默使用默认库。"""
    global _engine
    settings = get_settings()
    if not settings.database_configured:
        raise RuntimeError("DATABASE_URL 未配置，数据库功能不可用")
    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            # psycopg 的 libpq 参数：连接超时 2 秒，避免健康检查被长时间挂住
            connect_args={"connect_timeout": 2},
        )
        logger.info(
            "database engine created: %s", _engine.url.render_as_string(hide_password=True)
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


def check_database() -> DatabaseStatus:
    """实际尝试 `SELECT 1`。任何异常都归类为 unreachable，且不泄露 DSN。"""
    settings = get_settings()
    if not settings.database_configured:
        return DatabaseStatus(
            state="not_configured",
            detail="DATABASE_URL 未配置",
        )

    started = time.perf_counter()
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return DatabaseStatus(state="connected", detail="SELECT 1 成功", latency_ms=latency_ms)
    except Exception as exc:  # noqa: BLE001 - 健康检查需要吞掉所有连接异常
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        # 只回传异常类型与简短信息，绝不回传包含密码的 DSN
        detail = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
        logger.warning("database health check failed: %s", detail)
        return DatabaseStatus(state="unreachable", detail=detail, latency_ms=latency_ms)


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
