"""WearMind 后端应用入口。

当前提供：配置、日志、统一错误处理、健康检查。
数据库连接与 Alembic 迁移已就绪，但业务接口（衣柜 / 推荐 / Agent）尚未实现。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.api.v1.routes import health
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import check_database, dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("== %s v%s 启动，环境=%s ==", settings.app_name, settings.app_version, settings.app_env.value)
    logger.info("配置概览: %s", settings.safe_summary())

    if not settings.database_configured:
        logger.warning(
            "DATABASE_URL 未配置 —— 数据库功能不可用（不代表进程故障）"
        )
    else:
        db = check_database()
        log = logger.info if db.connected else logger.warning
        log("数据库状态: %s (%s)", db.state, db.detail)

    if settings.development_identity_allowed:
        # 刻意用 WARNING：这是"任何人都能以固定开发用户身份操作"的开放状态，
        # 日志里必须显眼，且明确说明它不是认证。
        logger.warning(
            "身份模式=%s —— 所有请求都使用配置中的固定开发用户，这不是认证；严禁用于生产",
            settings.auth_mode,
        )
    else:
        logger.info("身份模式=%s —— 需要身份的接口将返回 401", settings.auth_mode)

    yield

    dispose_engine()
    logger.info("== %s 已停止 ==", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format.value)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        description=(
            "WearMind —— AI 个人穿搭顾问后端。\n\n"
            f"当前阶段：Phase 2（衣物 CRUD + 仓储层用户隔离）。接口挂在 `{settings.api_v1_prefix}` 下。\n\n"
            "⚠️ 认证尚未实现：当前的用户身份来自**开发环境注入**"
            "（APP_ENV=development 且开启 DEV_USER_ENABLED），"
            "非开发环境调用需要身份的接口一律返回 401。"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    # 中间件注册顺序：后注册的在外层。CORS 必须在最外层，
    # 否则错误响应（如 500）会缺少 CORS 头，前端只能看到网络错误。
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)

    # 运维入口放在根路径；同时提供带版本前缀的别名，便于 API 客户端统一调用
    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/health",
            "api_prefix": settings.api_v1_prefix,
        }

    return app


app = create_app()
