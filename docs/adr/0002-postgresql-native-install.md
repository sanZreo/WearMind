# ADR 0002：PostgreSQL 采用原生安装（已实施）

- 状态：**已实施（2026-10-25 完成安装与初始化）**
- 日期：2026-10-25（2026-10-25 复测并更新软件源与安装包信息；同日执行安装）
- 阶段：Phase 0 → Phase 1 过渡
- 详细执行计划与执行记录见 [`docs/runbooks/postgresql-17-install.md`](../runbooks/postgresql-17-install.md)

## 实施结果（2026-10-25）

| 项 | 实际值 |
|---|---|
| 版本 | PostgreSQL **17.11** (x86_64-windows, msvc-19.44) |
| 安装目录 | `D:\PostgreSQL\17`（用户指定，非默认 C 盘） |
| 数据目录 | `D:\PostgreSQL\17\data` |
| 磁盘占用 | **1048.8 MB**（含 pgAdmin 4，见"偏差"） |
| Windows 服务 | `postgresql-x64-17`，Running，Automatic |
| 端口 | 5432 |
| 编码 | UTF8 |
| 认证 | `scram-sha-256`；`pg_hba.conf` 仅允许 127.0.0.1/32 与 ::1/128 |
| 系统 PATH | **未被修改**（安装器未写入），需用 `D:\PostgreSQL\17\bin\psql.exe` 全路径 |
| 应用角色/库 | `wearmind` / `wearmind`，由 `scripts/db_bootstrap.py` 幂等创建 |

### 实施偏差

1. `--enable-components server,commandlinetools` **未生效**，pgAdmin 4 仍被安装，
   实际占用 1048.8 MB 而非预估的约 500 MB。不影响功能；如需精简可单独卸载 pgAdmin。
2. 计划中的"由用户手动 GUI 安装"改为**脚本静默安装**（用户明确要求由我安装）：
   超级用户密码由脚本随机生成 32 位，写入 `var/secrets/`（已被 `.gitignore` 忽略），
   全程未打印、未进入命令文本与日志。
3. `listen_addresses` 保持默认 `*`。经核验 `pg_hba.conf` 只放行回环地址且无防火墙
   放行规则，外部实际无法连接，故未改动配置。

## 复测结论（2026-10-25）

- 再次确认**未安装**：`psql` 不在 PATH、四个标准目录均不存在、无 `postgres*` 服务、
  5432 空闲、`C:\ProgramData\PostgreSQL` 无残留 → 不存在重复安装风险。
- winget 可用（v1.29.380），且源已识别该包：
  `Found PostgreSQL 17 [PostgreSQL.PostgreSQL.17]`，版本 **17.11-5**。
- 安装包 `postgresql-17.11-5-windows-x64.exe`，394 MB，源站 HTTP 200，
  SHA256 `612c7f5400a003aaffa0372cb273eed52278f93c680ab911eb9cb2229e3229072`。
- 因此下文"风险：winget 包 ID 与源可用性需现场确认"已消除。
- 新增注意点：winget 对 exe 安装器可能走静默模式，导致 `postgres` 超级用户密码
  由安装器自定而非你设定。**推荐改为手动下载 + 图形界面安装**，让密码完全可控。

## 背景

实测结论（Phase 0 环境检查）：

- `psql` 不在 PATH
- `C:\Program Files\PostgreSQL` 等标准目录均不存在
- 无任何 `postgres*` Windows 服务
- 5432 端口空闲
- `winget list --id PostgreSQL.PostgreSQL.17` 无匹配结果

→ **本机确实没有安装 PostgreSQL**，不是"装了但没启动"。

同时实测：Docker CLI 存在（29.7.2）但 daemon 未运行；
Docker Desktop 的 Linux 引擎依赖 WSL2，而 WSL 状态在当前会话中无法验证。

## 决策

**原生安装 PostgreSQL 17，不使用 Docker。**

## 理由

1. 内存：总计 15.3 GB、空闲仅 4.1 GB。Docker Desktop 常驻约 1–2 GB，
   PostgreSQL 容器再加一层，会直接挤压 Ollama 与 Next.js dev server 的空间。
2. 故障面：Docker daemon 当前未运行，WSL 状态未知，两个不确定因素叠加。
3. 原生安装的 `psql` 直接在 PATH，排查问题最直接。

## 原定安装方案（已执行，保留备查）

### 方案 A：winget（推荐）

```powershell
winget install -e --id PostgreSQL.PostgreSQL.17
```

- 影响：安装 PostgreSQL 17 服务端 + pgAdmin；创建 Windows 服务 `postgresql-x64-17` 并设为自动启动；
  占用约 300–500 MB 磁盘（建议装在 D 盘，C 盘仅剩 86 GB）；
  安装过程会**要求你设置 `postgres` 超级用户密码**（由你输入，不要告知我）。
- 风险：静默模式下密码可能由安装器自定，你事后不知情 → 推荐改用方案 B，
  或 `winget install ... --interactive`。详见 `docs/runbooks/postgresql-17-install.md`。

### 方案 B：EDB 官方安装包

下载 <https://www.enterprisedb.com/downloads/postgres-postgresql-downloads> 的 Windows x86-64 版，
图形界面安装，勾选 Command Line Tools。

### 安装后需要执行的建库步骤（由你执行或授权我执行）

```powershell
# 1. 设置 PATH（或用完整路径 C:\Program Files\PostgreSQL\17\bin\psql.exe）
$env:Path += ";C:\Program Files\PostgreSQL\17\bin"

# 2. 建角色与库（密码自己定，不要发到聊天里）
psql -U postgres -c "CREATE ROLE wearmind LOGIN PASSWORD '你自己设定的密码';"
psql -U postgres -c "CREATE DATABASE wearmind OWNER wearmind ENCODING 'UTF8';"

# 3. 验证
psql -U wearmind -d wearmind -c "select version();"
```

### 然后写入 `apps/api/.env`

```
DATABASE_URL=postgresql+psycopg://wearmind:你自己设定的密码@localhost:5432/wearmind
```

写完后 `GET /health` 的 `database.state` 应从 `not_configured` 变为 `connected`。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| Docker Compose | daemon 未运行、WSL 状态未知、内存吃紧 |
| 云 PostgreSQL（Supabase/Neon） | 用户衣物与身材数据出境，与隐私目标直接冲突；仅可作临时验证 |
| SQLite | 后续要用的 `JSONB`、并发写、`ON CONFLICT` 语义、Alembic 迁移都要重写，迁移债过高 |

## 后果

- 在数据库就绪前，Phase 0 骨架**完全不依赖数据库**，可以独立运行与验收。
- 数据库一旦就绪，只需改 `.env` 一行，代码无需改动（`DATABASE_URL` 已完全外部化）。
- Alembic 初始化被推迟到数据库可用之后 —— 否则 `alembic init` 生成的脚手架无法验证是否可用。

## 修订记录

- **2026-10-25（Phase 2.5）**：决策 2 中"脚本生成密码并写入 `var/secrets/`"的做法已废止。
  两个明文文件删除，超级用户密码改由用户自有的密码管理器保管，
  `scripts/db_bootstrap.py` 改为交互式读取。理由：明文密码落盘本身就是风险，
  且该文件仅是 `apps/api/.env` 的冗余副本，删除不影响应用运行。
  "本机原生安装 + 连接串完全外部化"这一核心决策不变。
