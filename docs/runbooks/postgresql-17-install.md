# PostgreSQL 17 安装执行计划与记录

- 日期：2026-10-25
- 状态：**已执行完成** —— 实际结果见文末「执行记录」
- 关联：`docs/adr/0002-postgresql-native-install.md`
- 原则：本文不含任何真实密码；密码只在你的机器上由你输入，不进入命令行、日志、文档或 Git

---

## 0. 安装前实测事实（2026-10-25 复测）

| 检查项 | 实测结果 |
|---|---|
| `psql` 是否在 PATH | ❌ 不在 |
| `C:\Program Files\PostgreSQL` 等安装目录 | ❌ 全部不存在 |
| `C:\ProgramData\PostgreSQL`（数据目录残留） | ❌ 不存在 |
| `postgres*` Windows 服务 | ❌ 无 |
| 5432 端口 | ✅ 空闲 |
| 旧版本 PostgreSQL 残留 | ❌ 无 |

→ **确认是"从未安装"，不存在重复安装风险，也没有需要保留的既有数据库。**

## 1. 软件源与安装包可用性（实测）

| 项 | 结果 |
|---|---|
| winget | ✅ v1.29.380，`C:\Users\<YOUR_USERNAME>\AppData\Local\Microsoft\WindowsApps\winget.exe` |
| winget 源 | ✅ `msstore` + `winget` 均启用 |
| 包识别 | ✅ `Found PostgreSQL 17 [PostgreSQL.PostgreSQL.17]`，版本 **17.11-5** |
| 发布者 | PostgreSQL Global Development Group |
| 安装包 | EDB 官方 `postgresql-17.11-5-windows-x64.exe` |
| 包体积 | **413,001,200 字节 ≈ 394 MB** |
| SHA256 | `612c7f5400a003aaffa0372cb273eed52278f93c680ab911eb9cb2229e3229072` |
| 源站可达 | ✅ `get.enterprisedb.com` HTTP 200 |

> 注意：`raw.githubusercontent.com` 本机不可达。这只影响我查阅 winget 清单源码，
> **不影响安装** —— 安装包直接从 EDB 官方源下载，已验证 200。

## 2. 资源现状

| 资源 | 实测 | 对 PG 的影响 |
|---|---|---|
| C 盘 | 剩余 **86.3 GB** / 399.3 GB | 足够（PG 约占 0.5–1.2 GB） |
| D 盘 | 剩余 **223.8 GB** / 552.8 GB | 若想隔离，可装这里 |
| E 盘 | 剩余 **373.3 GB** / 931.5 GB | 项目所在盘 |
| 内存 | 总 **15.29 GB**，空闲 **3.87 GB**（已用 74.7%） | ⚠️ 偏紧但不阻塞 PG |
| 内存占用前 5 | WorkBuddy 822MB + 323MB、Defender 574MB、QQ 413MB、explorer 384MB、Memory Compression 365MB | 主要被开发工具与常驻应用占用 |

PG 默认配置（`shared_buffers=128MB`）常驻约 150–250 MB，**不会成为瓶颈**。
真正的内存冲突在别处：Ollama 跑 `qwen3.5:9b` 需约 6–7 GB，与 Next dev server、
PG、浏览器同时运行会逼近 15 GB 上限。建议 Ollama 只在需要时启动。

## 3. 两种安装方式（我推荐 B）

### 方案 A：winget 一键安装

```powershell
winget install -e --id PostgreSQL.PostgreSQL.17
```

- 优点：一条命令，包完整性由 winget 校验 SHA256。
- **缺点（这是关键）**：winget 对 exe 型安装器通常走静默模式，**超级用户密码可能由安装器
  自行决定或留空**，你事后不知道 `postgres` 的密码；也无法取消勾选 pgAdmin、无法自选安装目录。
- 若坚持用 A，建议加 `--interactive` 让安装器弹窗，由你亲自填密码与路径：

```powershell
winget install -e --id PostgreSQL.PostgreSQL.17 --interactive
```

### 方案 B：手动下载 + 图形界面安装（推荐）

```powershell
# 1. 下载（约 394 MB）
curl.exe -L -o "$env:USERPROFILE\Downloads\pg17-installer.exe" `
  "https://get.enterprisedb.com/postgresql/postgresql-17.11-5-windows-x64.exe"

# 2. 校验 SHA256（必须与 612c7f54...229072 一致）
Get-FileHash "$env:USERPROFILE\Downloads\pg17-installer.exe" -Algorithm SHA256 | Format-List

# 3. 手动双击运行，按下节选项安装
```

- 优点：**密码由你亲手设置、安装路径可选、可去掉不需要的组件**，全程可控。
- 代价：多几步点击。

## 4. 安装过程中的选项建议

| 步骤 | 建议 | 理由 |
|---|---|---|
| 安装目录 | `D:\PostgreSQL\17` | 数据目录会持续增长，放 D 盘不挤占系统盘；若只想简单，默认 `C:\Program Files\PostgreSQL\17` 也可（剩 86 GB 够用） |
| 组件勾选 | **只保留 PostgreSQL Server + Command Line Tools**，取消 **pgAdmin 4** 与 **Stack Builder** | 省约 500–700 MB；我们只用 `psql` 与 Python 驱动，不需要 GUI 管理工具 |
| 数据目录 | 跟随安装目录，或 `D:\PostgreSQL\data` | 便于单独备份/清理 |
| 端口 | **5432**（已确认空闲） | 与 `.env.example` 默认一致 |
| **超级用户密码** | **由你自己设，长度 ≥ 16，写入你的密码管理器** | 这是唯一无法找回的凭据；我不会索取、不会记录 |
| Locale / 编码 | 默认（`UTF8`），不要改 | 中文姓名、衣物标签需要 UTF8；改错会导致建库失败 |
| 服务账户 | 默认 `NT AUTHORITY\NetworkService` | 无需改动 |

> 安装器会要求管理员权限（UAC 弹窗），这是唯一会改动系统的地方：
> 创建 Windows 服务 `postgresql-x64-17` 并设为自动启动。

## 5. 安装后验证（不需要输入密码的部分）

```powershell
# 1. 版本
& "D:\PostgreSQL\17\bin\psql.exe" --version
# 期望：psql (PostgreSQL) 17.11

# 2. 服务状态
Get-Service postgresql-x64-17 | Select-Object Name,Status,StartType
# 期望：Running / Automatic

# 3. 端口监听
Get-NetTCPConnection -LocalPort 5432 -State Listen
# 期望：有记录，OwningProcess 指向 postgres.exe

# 4. 编码确认（会提示输入 postgres 密码）
& "D:\PostgreSQL\17\bin\psql.exe" -U postgres -h localhost -c "SHOW server_encoding;"
# 期望：UTF8
```

## 6. 建角色与建库（密码不出现在命令行）

**关键点**：不要用 `CREATE ROLE ... PASSWORD '明文'` —— 这条命令会留在 psql 历史、
PowerShell 历史、进程列表里。正确做法是用 psql 的 `\password`，它交互式读取并加密发送：

```powershell
& "D:\PostgreSQL\17\bin\psql.exe" -U postgres -h localhost

# 进入 psql 后依次执行：
CREATE ROLE wearmind LOGIN;
CREATE DATABASE wearmind OWNER wearmind;
\password wearmind          -- 交互式设置密码，两次输入，终端不回显
\q
```

验证（`wearmind` 自己的密码交互输入）：

```powershell
& "D:\PostgreSQL\17\bin\psql.exe" -U wearmind -h localhost -d wearmind -c "select current_user, current_database(), version();"
```

> 不建议设置 `PGPASSWORD` 环境变量或用 `~/.pgpass` 明文文件 —— 前者会进进程环境，
> 后者易被误提交。

## 7. 接入项目（唯一需要改的一处）

你自己创建 `apps/api/.env`（该文件已被 `.gitignore` 排除，且我实测确认忽略生效）：

```bash
cp .env.example apps/api/.env
```

然后编辑 `DATABASE_URL`（密码自己填，不要发给我）：

```
DATABASE_URL=postgresql+psycopg://wearmind:你的密码@localhost:5432/wearmind
```

重启后端后：

```powershell
curl http://127.0.0.1:8000/health
```

`database.state` 应从 `not_configured` 变为 **`connected`**，`latency_ms` 出现数值。
在此之前 `/health/ready` 返回 503 是正确行为（当前实测确认）。

## 8. 回滚方式（若想撤销）

```powershell
# 1. 停止并移除服务
Stop-Service postgresql-x64-17
& "D:\PostgreSQL\17\uninstall-postgresql.exe"     # 图形卸载
# 或用 winget：winget uninstall -e --id PostgreSQL.PostgreSQL.17

# 2. 清理残留（安装在默认路径时）
Remove-Item -Recurse "C:\Program Files\PostgreSQL"
Remove-Item -Recurse "C:\ProgramData\PostgreSQL"   # 注意：这会删除数据库数据
```

## 9. 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| 超级用户密码丢失 → 无法管理实例 | 高 | 安装时立即存入密码管理器；PG 无"找回"机制 |
| winget 静默安装导致密码未知 | 中 | 用方案 B，或 A + `--interactive` |
| 安装到 C 盘后数据增长挤占系统盘 | 低 | 装到 D 盘，或后续迁移数据目录 |
| 安装器要求重启 | 低 | EDB 安装器通常不需重启；若要求，先保存工作 |
| 内存紧张时 PG + Ollama + dev server 争抢 | 中 | PG 占用很小；限制 Ollama 只在需要时启动 |
| 端口 5432 后续被占用 | 低 | 当前空闲；如冲突改 `postgresql.conf` 的 `port` |
| 防火墙拦截 5432 | 低 | 仅本机访问，无需放行入站 |

## 10. 分工边界

**我（在你确认后）会做**：只读验证（版本、服务、端口、编码）、`/health` 连通性复测、
Alembic 脚手架初始化与首个迁移、`docs` 更新。

**只能你做**：下载/运行安装器、设置超级用户密码、输入 `wearmind` 角色密码。

**我不会做**：安装软件、改系统环境变量或服务配置、读取或索取任何密码、
把密码写进任何文件。

---

# 执行记录（2026-10-25 13:15–13:25）

用户指定安装到 `D:\PostgreSQL\17` 并要求由我执行，故采用**静默安装**而非本文第 3 节的方案 B。

## 实际步骤

| 步骤 | 命令要点 | 结果 |
|---|---|---|
| 1. 提权检查 | `WindowsPrincipal.IsInRole(Administrator)` | False → 安装需 UAC 提权 |
| 2. 下载 | `curl -L` 从 `get.enterprisedb.com` | HTTP 200，**413,001,200 字节**（16 秒） |
| 3. 哈希校验 | `Get-FileHash -Algorithm SHA256` | ✅ 与 winget 清单一致：`612c7f54…e329072` |
| 4. 签名校验 | `Get-AuthenticodeSignature` | ✅ Valid，CN=**EnterpriseDB Corporation**，DigiCert 时间戳 |
| 5. 安装 | `Start-Process -Verb RunAs -Wait`，参数见下 | 退出码 **0**，UAC 由用户确认 |
| 6. 服务验证 | `Get-Service postgresql-x64-17` | Running / Automatic |
| 7. 端口验证 | `Get-NetTCPConnection -LocalPort 5432` | 监听中（pid 27352） |
| 8. 连接验证 | `scripts/db_bootstrap.py --check` | ✅ 17.11 / UTF8 / scram-sha-256 |
| 9. 建角色与库 | `scripts/db_bootstrap.py --apply` | ✅ `wearmind` 角色 + `wearmind` 库 |
| 10. 应用连通性 | 以 `wearmind` 账号连接 | ✅ `user=wearmind db=wearmind encoding=UTF8` |
| 11. 接口验证 | `GET /health` | ✅ `database.state=connected`，3.0 ms |
| 12. 就绪检查 | `GET /health/ready` | ✅ **200**，`ready=true` |

安装参数：

```
--mode unattended --unattendedmodeui none
--superpassword <脚本随机生成 32 位，未打印>
--serverport 5432
--prefix D:\PostgreSQL\17
--datadir D:\PostgreSQL\17\data
--enable-components server,commandlinetools
```

## 与原计划的偏差

1. **pgAdmin 4 被一并安装**：`--enable-components` 未生效，实际占用 **1048.8 MB**（预估约 500 MB）。
   不影响功能，如需精简可单独卸载 `D:\PostgreSQL\17\pgAdmin 4`。
2. **密码处理**：原计划要求用户手动输入，实际改为脚本生成 32 位随机密码，
   写入 `var/secrets/`（`git check-ignore` 已确认忽略）。密码未出现在任何命令文本、
   stdout、日志或文档中。
   → **Phase 2.5 已废止此做法**：两个明文文件已删除，脚本改为交互式读取，见文末。
3. **`listen_addresses` 仍为 `*`**：这是 EDB 默认值。核验 `pg_hba.conf` 仅放行
   `127.0.0.1/32` 与 `::1/128`，且防火墙对 PostgreSQL 无入站放行规则，
   外部实际无法连接，因此**未改动配置**（避免动系统设置）。
4. **系统 PATH 未被修改**：安装器没有写 PATH，`psql` 需用全路径
   `D:\PostgreSQL\17\bin\psql.exe`。这是好事——符合"不改系统环境变量"的约束。

## 凭据处理（Phase 2.5 更新，已完成）

原计划把密码写入 `var/secrets/`，该目录下的两个明文文件现已**删除**：

- `pg-superuser.txt`（`postgres` 超级用户密码）→ 用户已备份至自有密码管理器
- `pg-wearmind.txt`（应用角色密码，与 `apps/api/.env` 中的值相同）→ 随之删除

当前凭据的唯一来源：

| 凭据 | 存放位置 |
|---|---|
| 应用角色 `wearmind` | `apps/api/.env` 的 `DATABASE_URL`（已被 `.gitignore` 忽略） |
| 超级用户 `postgres` | 用户自有的密码管理器，仓库内无副本 |

`scripts/db_bootstrap.py` 不再读取任何密码文件，改为 `getpass` 交互式输入；
新建角色时由操作者自行设定密码，脚本不生成、不保存、不打印。

若日后忘记超级用户密码，只能在 `pg_hba.conf` 临时改为 `trust` 后
`ALTER ROLE postgres PASSWORD '<新密码>';` 重置——**不要在命令行直接写密码**。
