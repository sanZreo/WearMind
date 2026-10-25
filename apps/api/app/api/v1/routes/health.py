"""健康检查路由。

职责边界：只报告事实，不做"假装健康"。
- GET /health       存活状态 + 依赖状态诊断（进程活着就 200）
- GET /health/ready 就绪状态（数据库不可用即 503）

两种状态被显式区分：
- process: 应用进程本身是否在跑（只要响应了就是 running）
- database: not_configured / connected / unreachable
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.db.session import check_database
from app.services.identity import identity_debug_info

router = APIRouter(tags=["health"])

PROCESS_STARTED_AT = time.time()


def _uptime_seconds() -> float:
    return round(time.time() - PROCESS_STARTED_AT, 1)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@router.get(
    "/health",
    summary="健康检查（存活 + 依赖诊断）",
    description=(
        "进程存活即返回 200。数据库状态如实放在 database 字段中，"
        "不会因为数据库未配置而伪装成已连接，也不会把 DSN 或密码返回给调用方。"
    ),
)
def health(response: Response) -> dict[str, Any]:
    settings = get_settings()
    db = check_database()

    overall = "ok" if db.state != "unreachable" else "degraded"
    if overall == "degraded":
        response.status_code = status.HTTP_200_OK  # 进程本身仍是活的

    return {
        "status": overall,
        "process": {
            "state": "running",
            "name": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env.value,
            "uptime_seconds": _uptime_seconds(),
        },
        "database": {
            "state": db.state,
            "detail": db.detail,
            "latency_ms": db.latency_ms,
        },
        "llm": {
            "provider": settings.llm_provider.value,
            "online_model_configured": settings.online_model_configured,
            "ollama_model": settings.ollama_model,
            "privacy_mode": settings.privacy_mode.value,
        },
        # 身份诊断：明确标注当前是"开发注入"而非"已认证"，
        # 避免看健康检查的人误以为系统已经接入认证。
        "identity": identity_debug_info(settings),
        "timestamp": _now(),
    }


@router.get(
    "/health/ready",
    summary="就绪检查（是否可承载业务）",
    description="只有数据库真实连通才返回 200；否则 503（DATABASE_URL 未配置或连不上）。",
)
def readiness(response: Response) -> dict[str, Any]:
    db = check_database()
    ready = db.connected
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "ready": ready,
        "database": {"state": db.state, "detail": db.detail},
        "timestamp": _now(),
    }
