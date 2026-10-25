#!/usr/bin/env python
"""WearMind 环境自检脚本（仅用标准库，无需安装任何依赖）。

用法：
    python scripts/check_env.py

退出码：
    0 = 无阻塞项（可能有警告）
    1 = 存在 BLOCKED 项，无法进入依赖该组件的阶段

设计原则：只报告实测事实。检查不到的项标 SKIP，绝不猜测成 OK。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OK, WARN, BLOCKED, SKIP = "OK", "WARN", "BLOCKED", "SKIP"
_rows: list[tuple[str, str, str]] = []


def add(name: str, status: str, detail: str) -> None:
    _rows.append((name, status, detail))


def run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, shell=False, check=False
        )
        return proc.returncode, (proc.stdout or proc.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 1, type(exc).__name__


def first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text else ""


def check_binary(name: str, cmd: list[str]) -> None:
    path = shutil.which(cmd[0])
    if not path:
        add(name, BLOCKED, f"未找到 {cmd[0]} 命令")
        return
    # Windows 上 npm / npx 是 .cmd 脚本，subprocess 直接执行会 FileNotFoundError，
    # 需要显式通过 cmd /c 调用（不使用 shell=True，避免注入风险）。
    if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
        run_cmd = ["cmd", "/c", path, *cmd[1:]]
    else:
        run_cmd = [path, *cmd[1:]]
    code, out = run(run_cmd)
    add(name, OK if code == 0 else WARN, first_line(out) or path)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        return sock.connect_ex((host, port)) == 0


def check_postgres() -> None:
    path = shutil.which("psql")
    port_up = port_open(5432)
    if path and port_up:
        _code, out = run(["psql", "--version"])
        add("PostgreSQL", OK, f"{first_line(out)}  | 5432 可连接")
        return
    if path:
        add("PostgreSQL", WARN, "psql 已安装但 5432 未监听（服务可能未启动）")
        return
    if port_up:
        add("PostgreSQL", WARN, "5432 有服务监听，但 psql 不在 PATH")
        return
    add("PostgreSQL", BLOCKED, "未安装，且 5432 无服务 —— 需要先安装（见 README）")


def check_ollama() -> None:
    path = shutil.which("ollama")
    port_up = port_open(11434)
    if not path:
        add("Ollama", SKIP, "未安装（本地模型为可选能力）")
        return
    if not port_up:
        add("Ollama", WARN, "已安装但服务未运行（11434 未监听），需手动启动")
        return
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=2) as sock:
            sock.sendall(b"GET /api/tags HTTP/1.1\r\nHost: localhost\r\n\r\n")
            data = sock.recv(4096).decode("utf-8", "ignore")
        if "200" in data.split("\r\n", 1)[0]:
            add("Ollama", OK, "服务运行中，11434 可访问")
        else:
            add("Ollama", WARN, "11434 有响应但未返回 200")
    except OSError as exc:
        add("Ollama", WARN, f"端口探测失败: {type(exc).__name__}")


def check_git_identity() -> None:
    code_name, name = run(["git", "config", "--global", "--get", "user.name"])
    code_mail, mail = run(["git", "config", "--global", "--get", "user.email"])
    if code_name == 0 and code_mail == 0 and name and mail:
        add("Git 身份", OK, f"{name} <{mail}>")
    else:
        add(
            "Git 身份",
            WARN,
            "user.name / user.email 未配置，提交会失败（请自行设置，脚本不代填）",
        )


def check_ports() -> None:
    busy = [p for p in (3000, 8000) if port_open(p)]
    if busy:
        add("开发端口", WARN, f"{busy} 已被占用，启动前需释放")
    else:
        add("开发端口", OK, "3000 与 8000 均空闲")


def check_env_file() -> None:
    api_env = ROOT / "apps" / "api" / ".env"
    if api_env.exists():
        text = api_env.read_text(encoding="utf-8", errors="ignore")
        has_key = any(
            line.split("=", 1)[1].strip()
            for line in text.splitlines()
            if line.startswith("ONLINE_MODEL_API_KEY=") and "=" in line
        )
        add("apps/api/.env", OK, f"存在；API Key 已填写={has_key}")
    else:
        add("apps/api/.env", SKIP, "不存在（正常：复制 .env.example 后按需填写）")


def check_venv() -> None:
    venv = ROOT / ".venv"
    if venv.exists():
        add("Python 虚拟环境", OK, str(venv))
    else:
        add("Python 虚拟环境", WARN, "未创建，执行 `uv sync` 即可生成")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    add("Python", OK if sys.version_info[:2] >= (3, 12) else BLOCKED, sys.version.split()[0])
    check_binary("uv", ["uv", "--version"])
    check_binary("Node.js", ["node", "--version"])
    check_binary("npm", ["npm", "--version"])
    check_binary("Git", ["git", "--version"])
    check_git_identity()
    check_postgres()
    check_ollama()
    check_ports()
    check_venv()
    check_env_file()

    width = max(len(name) for name, _, _ in _rows) + 2
    print("\nWearMind 环境自检")
    print("=" * 78)
    for name, status, detail in _rows:
        print(f"{name.ljust(width)} {status.ljust(8)} {detail}")
    print("=" * 78)

    blocked = [r for r in _rows if r[1] == BLOCKED]
    warns = [r for r in _rows if r[1] == WARN]
    print(f"合计 {len(_rows)} 项：OK={sum(r[1] == OK for r in _rows)} "
          f"WARN={len(warns)} BLOCKED={len(blocked)} SKIP={sum(r[1] == SKIP for r in _rows)}")

    if blocked:
        print("\n阻塞项：")
        for name, _, detail in blocked:
            print(f"  - {name}: {detail}")
        return 1

    print("\n无阻塞项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
