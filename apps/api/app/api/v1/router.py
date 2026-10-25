"""v1 版本路由聚合。

已挂载：健康检查（同时保留根路径 /health 作为运维入口）、衣物 CRUD。
后续阶段在此挂载：uploads / recommendations / feedback / preferences。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import health, items

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(items.router)
