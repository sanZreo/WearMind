"""Alembic 运行环境。

关键设计：
1. **连接串只来自应用的 Settings**（环境变量 / `apps/api/.env`），
   `alembic.ini` 里不存任何 URL。这里不打印 URL —— 只在异常时给出脱敏提示。
2. 直接 `create_engine(...)` 而不是 `engine_from_config()`，
   避免把 DSN 塞进 Config 后触发 configparser 的 `%` 转义问题
   （密码含 `%` 时会静默解析错误）。
3. `target_metadata = Base.metadata`，并 `import app.models` 触发**全部模型注册**。
4. 只做迁移，不参与应用启动 —— 应用启动时**不会**自动执行 upgrade。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# 让 `app` 可被导入：alembic 从 apps/api 运行时，cwd 已在 sys.path；
# 但从仓库根运行时不一定，故显式补齐。
API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.config import get_settings
from app.db.base import Base
from app.models import Item, User  # noqa: F401  —— 导入即注册，勿删

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
DATABASE_URL = settings.database_url

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 未配置，无法执行迁移。\n"
        "请设置环境变量，或在 apps/api/.env 中配置（该文件已被 .gitignore 忽略）。"
    )

target_metadata = Base.metadata

# 自动生成时忽略的表：Alembic 自己的版本表不应出现在迁移里
EXCLUDE_TABLES = {"alembic_version"}


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    # Alembic 自己的版本表不属于业务 schema，不应出现在自动生成的迁移里
    return not (type_ == "table" and name in EXCLUDE_TABLES)


def _common_context_kwargs() -> dict:
    return {
        "target_metadata": target_metadata,
        "include_object": _include_object,
        # 检测字段类型变化（如 VARCHAR(32) -> VARCHAR(64)）
        "compare_type": True,
        # 检测 server_default 变化
        "compare_server_default": True,
    }


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连库。"""
    context.configure(
        url=DATABASE_URL,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_common_context_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：真实连接数据库执行迁移。"""
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, **_common_context_kwargs())
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
