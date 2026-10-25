#!/usr/bin/env python
"""PostgreSQL 本地实例引导脚本（WearMind Phase 1 前置）。

职责：
1. 用超级用户连接，打印实例基础信息（版本/编码/监听/加密方式）。
2. 幂等创建应用角色 `wearmind` 与数据库 `wearmind`。

用法：
    # 只看信息，不做任何修改
    uv run python scripts/db_bootstrap.py --check

    # 创建角色与数据库（已存在则跳过）
    uv run python scripts/db_bootstrap.py --apply

超级用户密码来源（按优先级）：
    1. 环境变量 PGPASSWORD —— 仅供 CI / 临时场景
    2. 交互式输入（getpass，终端不回显）

安全约定（Phase 2.5 起，本脚本已不再读取任何密码文件）：
    - 不含硬编码凭据，也不从磁盘读取密码。
    - 超级用户密码只经变量传递，不进入 stdout / 日志 / 异常信息。
    - 需要新建角色时，密码由操作者交互式输入，脚本既不生成也不打印；
      输入后请同步填入 apps/api/.env 的 DATABASE_URL。
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

import psycopg
import psycopg.sql

HOST = os.environ.get("PGHOST", "127.0.0.1")
PORT = int(os.environ.get("PGPORT", "5432"))
SUPERUSER = os.environ.get("PGSUPERUSER", "postgres")

APP_ROLE = "wearmind"
APP_DB = "wearmind"

MIN_APP_PASSWORD_LEN = 12


def read_superuser_password() -> str:
    """取超级用户密码：环境变量优先，否则交互式输入。绝不读文件。"""
    env_pw = os.environ.get("PGPASSWORD")
    if env_pw:
        return env_pw
    if not sys.stdin.isatty():
        sys.exit(
            "[FAIL] 需要超级用户密码，但当前不是交互式终端。\n"
            "       请直接运行本脚本（会提示输入），或临时设置 PGPASSWORD 环境变量。"
        )
    print(f"[输入] PostgreSQL 超级用户（{SUPERUSER}）密码，输入不回显：")
    try:
        password = getpass.getpass("password: ")
    except (KeyboardInterrupt, EOFError):
        sys.exit("\n[FAIL] 已取消。")
    if not password:
        sys.exit("[FAIL] 密码为空。")
    return password


def prompt_new_role_password() -> str:
    """新建角色时由操作者设定密码：脚本不生成、不保存、不打印。"""
    print(f"[输入] 角色 {APP_ROLE} 尚不存在，请为其设定密码（不回显，建议 32 位随机串）：")
    try:
        first = getpass.getpass("password: ")
        second = getpass.getpass("confirm : ")
    except (KeyboardInterrupt, EOFError):
        sys.exit("\n[FAIL] 已取消。")
    if first != second:
        sys.exit("[FAIL] 两次输入不一致。")
    if len(first) < MIN_APP_PASSWORD_LEN:
        sys.exit(f"[FAIL] 密码长度不足 {MIN_APP_PASSWORD_LEN} 位。")
    return first


def connect(dbname: str, password: str, user: str = SUPERUSER) -> psycopg.Connection:
    return psycopg.connect(
        host=HOST, port=PORT, dbname=dbname, user=user, password=password, connect_timeout=10
    )


def show_info(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("select version()")
        print(f"server_version      : {cur.fetchone()[0]}")
        for name in ("server_encoding", "listen_addresses", "port", "password_encryption",
                     "data_directory"):
            cur.execute(f"show {name}")
            print(f"{name:<20}: {cur.fetchone()[0]}")
        cur.execute("select rolname from pg_roles where rolcanlogin order by 1")
        print(f"login_roles         : {', '.join(r[0] for r in cur.fetchall())}")
        cur.execute("select datname from pg_database order by 1")
        print(f"databases           : {', '.join(r[0] for r in cur.fetchall())}")


def ensure_role_and_db(conn: psycopg.Connection) -> str:
    """幂等创建角色与数据库，返回本次可验证的应用角色密码。

    角色已存在时返回空串：此时密码不在脚本掌握范围内，
    它应当且仅应当由 apps/api/.env 的 DATABASE_URL 管理。
    """
    app_pw = ""

    with conn.cursor() as cur:
        cur.execute("select 1 from pg_roles where rolname = %s", (APP_ROLE,))
        if cur.fetchone() is not None:
            print(f"[SKIP] 角色 {APP_ROLE} 已存在（密码由 apps/api/.env 管理，本脚本不读取）")
        else:
            app_pw = prompt_new_role_password()
            cur.execute(
                psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    psycopg.sql.Identifier(APP_ROLE), psycopg.sql.Literal(app_pw)
                )
            )
            print(f"[OK]   已创建角色 {APP_ROLE}（LOGIN，密码由你设定，未显示）")

        cur.execute("select 1 from pg_database where datname = %s", (APP_DB,))
        if cur.fetchone() is None:
            cur.execute(
                psycopg.sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    psycopg.sql.Identifier(APP_DB), psycopg.sql.Identifier(APP_ROLE)
                )
            )
            print(f"[OK]   已创建数据库 {APP_DB}（owner={APP_ROLE}）")
        else:
            print(f"[SKIP] 数据库 {APP_DB} 已存在")

    if app_pw:
        print()
        print("下一步：把该密码填入 apps/api/.env（该文件已被 .gitignore 忽略）：")
        print(f"  DATABASE_URL=postgresql+psycopg://{APP_ROLE}:<你的密码>@{HOST}:{PORT}/{APP_DB}")
        print("同时存入密码管理器。脚本不保存、不回显该密码，丢了只能 ALTER ROLE 重置。")
        print()

    return app_pw


def verify_app_login(password: str) -> bool:
    try:
        with connect(APP_DB, password, user=APP_ROLE) as conn, conn.cursor() as cur:
            cur.execute(
                "select current_user, current_database(), current_setting('server_encoding')"
            )
            user, db, enc = cur.fetchone()
            print(f"[OK]   应用账号连通性验证：user={user} db={db} encoding={enc}")
            return True
    except psycopg.Error as exc:
        # 只暴露异常类型与 SQLSTATE，不回显密码
        print(f"[FAIL] 应用账号连接失败：{type(exc).__name__} {getattr(exc, 'sqlstate', '')}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="WearMind PostgreSQL bootstrap")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="只检查，不做修改")
    group.add_argument("--apply", action="store_true", help="创建角色与数据库（幂等）")
    args = parser.parse_args()

    super_pw = read_superuser_password()

    try:
        with connect("postgres", super_pw) as conn:
            conn.autocommit = True
            print("=== 实例信息 ===")
            show_info(conn)

            if args.check:
                with conn.cursor() as cur:
                    cur.execute("select 1 from pg_roles where rolname = %s", (APP_ROLE,))
                    print(f"=== 应用角色 {APP_ROLE} 是否存在: {'是' if cur.fetchone() else '否'}")
                    cur.execute("select 1 from pg_database where datname = %s", (APP_DB,))
                    print(f"=== 应用库 {APP_DB} 是否存在: {'是' if cur.fetchone() else '否'}")
                return 0

            print("=== 创建角色与数据库 ===")
            app_pw = ensure_role_and_db(conn)

        if app_pw:
            print("=== 连通性验证 ===")
            return 0 if verify_app_login(app_pw) else 1
        return 0

    except psycopg.OperationalError as exc:
        msg = str(exc)
        print(f"[FAIL] 无法连接 PostgreSQL {HOST}:{PORT} -> {type(exc).__name__}")
        # 只提示常见原因，不回显可能含密码的连接串
        if "password authentication failed" in msg:
            print("       原因：超级用户密码不正确（请用密码管理器中的记录重试）")
        elif "timeout" in msg.lower():
            print("       原因：连接超时（服务未启动或端口被拦）")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
