# 数据库接入前检查报告

- 项目：WearMind
- 日期：2026-10-25 13:28–13:32
- 阶段：Phase 0 收尾 → Phase 1 前置
- 性质：**只读检查**。未安装软件、未修改 Windows 服务、未创建或删除数据库、未修改 `.env`、未初始化 Alembic
- 关联文档：[架构规划](../planning/00-architecture-plan.md)、[ADR 0002](../adr/0002-postgresql-native-install.md)、[安装执行记录](../runbooks/postgresql-17-install.md)

> **重要前提说明**
> `wearmind` 角色、`wearmind` 数据库、`apps/api/.env` **均已存在**，由上一轮（2026-10-25 13:15–13:25）
> 按用户授权安装数据库时创建。本次检查**没有重复创建、没有覆盖任何数据**。
> 若期望"由用户手动创建"，需要的是重建而非新建。

---

## A. PostgreSQL 版本与安装路径

| 项 | 实测值 | 取证方式 |
|---|---|---|
| 版本 | **17.11** (x86_64-windows, compiled by msvc-19.44.35229, 64-bit) | `psql --version` + 服务端 `select version()` |
| 安装路径 | **`D:\PostgreSQL\17`** | 目录存在 + 注册表 ImagePath 双重确认 |
| 数据目录 | `D:\PostgreSQL\17\data` | `SHOW data_directory` |
| 服务注册路径 | `"D:\PostgreSQL\17\bin\pg_ctl.exe" runservice -N "postgresql-x64-17" -D "D:\PostgreSQL\17\data" -w` | `HKLM:\SYSTEM\CurrentControlSet\Services\postgresql-x64-17` |
| `psql` 可用性 | ✅ 可用，但**不在 PATH** | `Get-Command psql` 无结果；`D:\PostgreSQL\17\bin\psql.exe` 存在 |

说明：非管理员进程读取 `Get-Process postgres | Select Path` 返回空，故改用注册表 ImagePath
交叉验证，避免"目录存在即认为装在这里"的误判。实际路径与预期 `D:\PostgreSQL\17` **一致**。

## B. Windows 服务和端口状态

| 检查项 | 结果 |
|---|---|
| 服务名 | `postgresql-x64-17` **存在** |
| 服务状态 | `Running` |
| 启动类型 | `Automatic`（开机自启） |
| 5432 端口 | ✅ 监听中，`0.0.0.0:5432` 与 `[::]:5432`，PID 27352 |

结论：服务正常运行，**无需任何修复动作**，本节不涉及服务配置变更。

补充（安全面）：`listen_addresses` 为默认 `*`，但 `pg_hba.conf` 仅放行
`127.0.0.1/32` 与 `::1/128`，且防火墙无 PostgreSQL 入站放行规则 —— 外部实际不可达。
此项为上一轮已核验结论，本轮未改动任何配置。

## C. `wearmind` 角色及数据库状态

| 对象 | 状态 | 证据 |
|---|---|---|
| 角色 `wearmind` | **已存在**（可登录） | `login_roles: postgres, wearmind` |
| 数据库 `wearmind` | **已存在** | `databases: postgres, template0, template1, wearmind` |
| `apps/api/.env` | **已存在** | 文件存在，`DATABASE_URL` 指向本地 `wearmind` 库 |

实例基础参数：

| 参数 | 值 |
|---|---|
| `server_encoding` | `UTF8` |
| `password_encryption` | `scram-sha-256` |
| `port` | `5432` |
| `data_directory` | `D:/PostgreSQL/17/data` |

密码处理说明：

- 未向用户索取任何密码。
- 未将密码写入命令行参数、日志、文档或 Git。
- 检查脚本从 `var/secrets/` 读取密码，仅在进程内使用，不打印、不回显。
- 本次为只读查询，**未执行任何 `CREATE ROLE ... PASSWORD '...'`**。

## D. FastAPI 数据库接入代码现状

| 能力 | 现状 | 位置 |
|---|---|---|
| 数据库配置 | ✅ 已有。`DATABASE_URL` 空值视为"未配置"；带协议白名单校验（`postgresql+psycopg://` / `postgresql://`） | `apps/api/app/core/config.py` |
| SQLAlchemy 依赖 | ✅ `sqlalchemy>=2.1.6`，实装 **2.1.6** | `apps/api/pyproject.toml` |
| PostgreSQL 驱动 | ✅ `psycopg[binary]>=3.3.6`，实装 **3.3.6** | 同上 |
| 连接管理 | ✅ 惰性 Engine、`pool_pre_ping`、`pool_size=5`、`connect_timeout=2`、`get_session_factory()`、`dispose_engine()` | `apps/api/app/db/session.py` |
| `GET /health` | ✅ 实测 **200**，`database.state=connected`，延迟 **2.5 ms** | `apps/api/app/api/v1/routes/health.py` |
| `GET /health/ready` | ✅ 实测 **200**，`ready=true` | 同上 |
| Alembic 配置 | ❌ **完全缺失**：无 `alembic.ini`、无迁移目录 | — |
| ORM 模型 | ❌ 无 `app/models/` 目录 | — |

实时接口输出（节选）：

```json
// GET /health  -> 200
{
  "status": "ok",
  "process": { "state": "running", "name": "WearMind", "version": "0.1.0", "env": "development", "uptime_seconds": 2.5 },
  "database": { "state": "connected", "detail": "SELECT 1 成功", "latency_ms": 2.5 },
  "llm": { "provider": "online", "online_model_configured": false, "ollama_model": "qwen3.5:9b", "privacy_mode": "hybrid" },
  "timestamp": "2026-10-25T05:28:34+00:00"
}
```

```json
// GET /health/ready  -> 200
{ "ready": true, "database": { "state": "connected", "detail": "SELECT 1 成功" }, "timestamp": "2026-10-25T05:28:34+00:00" }
```

响应泄漏检查：对 `password` / `postgresql+psycopg` / `wearmind:` 三个模式匹配，命中数 **0**。

设计确认：`/health` 与 `/health/ready` 的语义区分实现正确 —— 进程存活即 200，
只有数据库真实连通 `ready` 才为 true。接入真实数据库后该设计依然成立，**无需修改**。

## E. 发现的问题

### E-1 两处过期文案（不影响功能，会误导后来者）

| 位置 | 过期表述 | 现状 |
|---|---|---|
| `apps/api/app/db/session.py` 模块 docstring | "本阶段（Phase 0）**没有** PostgreSQL 可用" | 已有 PG 17.11 且连通 |
| 同上 `check_database()` | `detail="DATABASE_URL 未配置（Phase 0 尚未安装 PostgreSQL）"` | 与事实不符 |
| `apps/api/app/api/v1/routes/health.py` `/health/ready` description | "Phase 0 无数据库，因此预期为 503" | 实际已返回 200 |

**本轮按约束未修改**，建议 Phase 1 一并改为中性表述（如"未配置 DATABASE_URL"）。

### E-2 `psql -c` 在本机工具环境被拦截

现象：在自动化 PowerShell 环境中执行 `psql -c "select 1"` 报 `'cat' 不是内部或外部命令`。

- 这是运行环境包装层的问题，**不是数据库问题**。
- 用户在普通 PowerShell 窗口中使用 `psql` 正常，不受影响。
- 影响面：脚本化 SQL 无法走 psql CLI，已改用 `psycopg` 绕过（`scripts/db_bootstrap.py`）。

### E-3 密码文件仍为明文

`var/secrets/pg-superuser.txt`、`var/secrets/pg-wearmind.txt` 为明文，已被 `.gitignore` 忽略
（`git check-ignore` 实测命中），不会误提交，但仍是本机明文凭据，建议尽快转移到密码管理器。

### E-4 无迁移机制

数据库已可用，但没有任何 schema 版本管理。此时若直接建表，后续变更将无法追踪。
应在写第一张业务表之前先立起 Alembic。

## F. 用户接下来需要手动执行的步骤

数据库侧**已无必须操作**（库、角色、连接串均就绪）。剩余为安全与使用习惯项：

### F-1 转移并删除明文密码文件

将 `var/secrets/pg-superuser.txt` 中的 postgres 密码抄入密码管理器，然后删除该文件。
如需更换密码：

```powershell
D:\PostgreSQL\17\bin\psql.exe -U postgres -h localhost
# 进入 psql 后：
\password postgres
\q
```

`\password` 交互读取并加密发送，不会留在命令历史与日志中。

### F-2 可选：让 psql 在当前终端可用

```powershell
$env:Path += ";D:\PostgreSQL\17\bin"
```

仅对当前窗口生效，**不修改系统环境变量**。

### F-3 可选：验证中文存储

```powershell
D:\PostgreSQL\17\bin\psql.exe -U wearmind -d wearmind -h localhost -c "select '衬衫'::text;"
```

## G. 下一阶段计划

按依赖顺序，Phase 1 第一批：

| 序号 | 任务 | 验收 |
|---|---|---|
| 1 | 修正 E-1 的两处过期文案 | 全项目无 "Phase 0 尚未安装 PostgreSQL" 类表述 |
| 2 | Alembic 初始化：`alembic.ini` + `env.py` 从 `Settings.database_url` 读取，**不把 DSN 写进 ini** | `alembic current` 可执行并正确连库 |
| 3 | 建第一批表 `users`、`items`（衣物） | 迁移生成且 `\dt` 可见 |
| 4 | 迁移双向验证 | `upgrade head` 与 `downgrade base` 均可成功 |
| 5 | 数据隔离最小验证 | 断言"用户 A 查不到用户 B 的衣物"的测试通过 |

刻意只做两张表：先跑通"迁移 → 建表 → 回滚"闭环，再逐步加表，避免一次性铺开 schema。

---

## 检查方法附录

| 检查项 | 实际执行的命令/方式 |
|---|---|
| 服务与端口 | `Get-Service postgresql-x64-17`、`Get-NetTCPConnection -LocalPort 5432` |
| 安装路径 | 目录探测 + `Get-ItemProperty HKLM:\...\postgresql-x64-17` 的 `ImagePath` |
| psql | `Get-Command psql`、`D:\PostgreSQL\17\bin\psql.exe --version` |
| 实例参数 | `scripts/db_bootstrap.py --check`（经 psycopg 执行只读查询） |
| 角色/库存在性 | `pg_roles` / `pg_database` 只读查询 |
| 接口连通 | 临时启动 uvicorn，`curl /health`、`/health/ready`，验证后停止并释放端口 |
| 依赖版本 | 虚拟环境内 `import sqlalchemy, psycopg, alembic` 打印 `__version__` |
| 敏感信息 | 对接口响应做 `password`/DSN 模式匹配，计数为 0 |

**本阶段到此停止，未执行上述 Phase 1 的任何一步。**
