# WearMind

AI 个人穿搭顾问。用照片或文字建立数字衣柜，结合天气、场景与个人偏好生成穿搭建议。

> **当前状态：Phase 0（项目骨架）**
> 只有可运行的前后端骨架与健康检查，**没有任何业务功能**。
> 衣柜、登录、AI 推荐、定时任务均未实现。

## 目录结构

```
WearMind/
├── apps/
│   ├── web/          Next.js 16 前端（App Router + TypeScript + Tailwind）
│   ├── api/          FastAPI 后端
│   │   ├── app/api/v1/{routes,schemas}/   路由与请求/响应模型
│   │   ├── app/core/                     配置 / 日志 / 错误 / UserContext
│   │   ├── app/repositories/             仓储层（以 UserContext 为隔离边界）
│   │   ├── app/services/                 业务服务（身份解析等）
│   │   ├── app/models/                   ORM 模型
│   │   └── migrations/                   Alembic 迁移
│   └── worker/       定时任务进程（占位，Phase 5 才实现）
├── packages/
│   └── contracts/    OpenAPI → TS 类型契约（Phase 1 实现生成器）
├── docs/
│   ├── planning/     架构规划文档
│   ├── design/       数据模型与接口设计
│   ├── adr/          架构决策记录
│   ├── runbooks/     操作手册
│   └── reports/      阶段性检查/交付报告
├── scripts/          开发辅助脚本（环境自检、数据库引导等）
├── tests/            跨应用测试（E2E 等）
├── var/              本地运行数据（已 git 忽略）
├── pyproject.toml    uv workspace 根
├── .env.example      环境变量模板
└── README.md
```

与最初设想的差异及理由：

| 调整 | 理由 |
|---|---|
| Python 用 **uv workspace** 管理，`.venv` 放在仓库根 | 只有一个虚拟环境，`apps/api` 与 `apps/worker` 共享依赖版本，避免两套解释器打架；每个 app 仍保留独立 `pyproject.toml` |
| `packages/shared` 改为 `packages/contracts` | 本项目没有需要前后端共享的运行时逻辑，只有类型契约 |
| 再加 `tests/`（根级） | `apps/api/tests` 是单元/集成测试；根级 `tests/` 放跨应用 E2E，避免混淆 |

## 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | `>=3.12,<3.14` | 已验证 3.13.14 |
| Node.js | 22.x | 已验证 22.22.2 |
| uv | 0.9+ | 已验证 0.12.9 |
| PostgreSQL | 17.11 | ✅ 已安装于 `D:\PostgreSQL\17`，服务 `postgresql-x64-17` 自启 |
| Ollama | 可选 | 已验证已安装，服务未启动 |

自检：

```bash
python scripts/check_env.py
```

## 本地启动

### 0. 准备配置

```bash
cp .env.example apps/api/.env          # 已存在则跳过
uv run python scripts/db_bootstrap.py --apply   # 建角色/库并写入 DATABASE_URL
```

不创建 `.env` 也能启动 —— 此时配置走默认值，`/health` 会如实报告
`database.state = "not_configured"`。**不要**把真实密钥写进任何入库文件。

### 1. 后端

```bash
uv sync                      # 首次：创建 .venv 并安装依赖
cd apps/api
uv run uvicorn app.main:app --reload --port 8000
```

- 健康检查：<http://localhost:8000/health>
- 接口文档：<http://localhost:8000/docs>
- 就绪检查：<http://localhost:8000/health/ready>（无数据库时预期 **503**，属正确行为）

#### 调用需要身份的接口（衣柜 API）

认证**尚未实现**。本地要让 `/api/v1/items` 可用，必须在 `apps/api/.env` 中启用开发身份：

```ini
APP_ENV=development
DEV_USER_ENABLED=true
DEV_USER_PUBLIC_ID=8f3a1c2e-0b7d-4e5f-9a61-2c4d8e7b1f30
DEV_USER_DISPLAY_NAME=本地开发用户
```

- 三个条件同时满足才生效：`APP_ENV=development`、`DEV_USER_ENABLED=true`、合法 UUID。
- 任一不满足，需要身份的接口返回 **401**（不会退化成某个默认用户）。
- `APP_ENV=production` 且 `DEV_USER_ENABLED=true` 时，应用**拒绝启动**。
- 该用户会在首次请求时按 `DEV_USER_PUBLIC_ID` 幂等创建（不会重复创建）。
- **这不是认证。** 请求体里的 `user_id` 会被 422 拒绝，查询参数/请求头也无法改变身份。

```bash
curl -s http://localhost:8000/api/v1/items
curl -s -X POST http://localhost:8000/api/v1/items \
  -H "Content-Type: application/json" \
  -d '{"name":"白色牛津纺衬衫","category":"top","color":"白色"}'
```

`/health` 的 `identity.auth_mode` 会如实显示当前是 `development_identity` 还是 `unauthenticated`。

### 2. 前端

```bash
cd apps/web
npm install                  # 首次
npm run dev                  # http://localhost:3000
```

### 3. 数据库迁移

**必须从 `apps/api` 目录运行**，否则读不到该目录下的 `.env`。

```bash
cd apps/api
uv run alembic current          # 查看当前版本
uv run alembic upgrade head     # 迁移到最新
uv run alembic downgrade -1     # 回退一个版本
uv run alembic check            # 校验模型与数据库是否一致（不产生变更）
```

连接串只来自 `Settings`（环境变量 / `apps/api/.env`），`alembic.ini` 中**不含任何 URL**。

新增模型后必须在 `app/models/__init__.py` 中 import —— 否则自动生成的迁移会静默漏表；
`tests/test_model_registry.py` 会拦住这类遗忘。

> 应用启动时**不会**自动执行迁移。迁移是部署动作，不是启动副作用。

### 4. Worker（可选）

```bash
cd apps/worker
uv run python -m wearmind_worker
```

当前会打印"没有已注册任务"后退出 —— 这是 Phase 0 的预期行为，不是故障。

### 5. 测试

```bash
cd apps/api && uv run pytest -q
```

- 应用层测试（健康检查、配置）不依赖数据库，会把 `DATABASE_URL` 置空模拟"未配置"。
- 数据库集成测试从 `apps/api/.env` 读取连接串，每个用例跑在最终 rollback 的外层事务里，
  **不会向数据库写入数据**；未执行迁移时会被 skip 而非 fail。
- API 测试把 `get_db_session` 覆盖为同一个事务内 Session，因此路由里的 `commit()`
  退化为 SAVEPOINT 释放，测试结束统一 rollback —— 同样不落库。
  ⚠️ 但 `Session.rollback()` 会连带撤掉外层事务（已实测），所以仓储层只在真正的
  数据库异常时才回滚，"命中 0 行"这类正常分支不调用 rollback。
- 数据模型与隔离测试见 `tests/test_data_isolation.py`，设计说明见
  [`docs/design/phase1-users-items.md`](docs/design/phase1-users-items.md)。
- 仓储隔离与 CRUD 见 `tests/test_item_repository.py`、`tests/test_items_api.py`。

## 衣物 API（/api/v1/items）

| 方法 | 路径 | 成功 | 说明 |
|---|---|---|---|
| POST | `/api/v1/items` | 201 | 归属由服务端身份决定 |
| GET | `/api/v1/items` | 200 | 只返回自己的；`limit`(1–100) / `offset` |
| GET | `/api/v1/items/{id}` | 200 | 他人或不存在均 **404** |
| PATCH | `/api/v1/items/{id}` | 200 | 局部更新；`color`/`image_ref` 传 `null` 即清空 |
| DELETE | `/api/v1/items/{id}` | 204 | 无响应体；他人或不存在均 404 |

响应不含 `user_id`；请求体出现 `user_id`、`id`、`created_at` 等未声明字段一律 422。
**越权访问与他人资源不存在返回完全相同的 404**，不泄露资源存在性。

## 关于 PostgreSQL（已安装）

本机已安装 **PostgreSQL 17.11**，原生安装，不依赖 Docker。实测状态：

| 项 | 值 |
|---|---|
| 安装目录 | `D:\PostgreSQL\17` |
| 数据目录 | `D:\PostgreSQL\17\data` |
| Windows 服务 | `postgresql-x64-17`（Running / 自动启动） |
| 端口 | 5432 |
| 编码 | UTF8，`scram-sha-256` 认证 |
| `psql` | **不在系统 PATH**（安装器未改环境变量），需用完整路径 `D:\PostgreSQL\17\bin\psql.exe` |

应用账号 `wearmind` 与数据库 `wearmind` 由脚本幂等创建：

```bash
uv run python scripts/db_bootstrap.py --check   # 只读检查
uv run python scripts/db_bootstrap.py --apply   # 创建角色与库（已存在则跳过）
```

数据库凭据**不落盘、不入库**：

- `apps/api/.env` 的 `DATABASE_URL` —— 应用角色的唯一凭据来源（文件被 `.gitignore` 忽略）
- `postgres` 超级用户密码 —— 只保存在你自己的密码管理器里，仓库内不留任何副本

`scripts/db_bootstrap.py` 以交互方式（`getpass`，终端不回显）询问密码，
**不生成、不保存、不打印任何密码**，也不读取任何密码文件。

安装过程与偏差记录见 [`docs/runbooks/postgresql-17-install.md`](docs/runbooks/postgresql-17-install.md)。

## 健康检查的语义

`GET /health` 把两件事分开报告，不允许混淆：

```json
{
  "status": "ok",
  "process":  { "state": "running", "uptime_seconds": 12.3 },
  "database": { "state": "not_configured", "detail": "...", "latency_ms": null },
  "llm": { "provider": "online", "online_model_configured": false, "privacy_mode": "hybrid" },
  "identity": { "auth_mode": "unauthenticated", "development_identity_allowed": false }
}
```

| 字段 | 含义 |
|---|---|
| `status` | `ok` = 进程正常；`degraded` = 进程正常但依赖不可用 |
| `process.state` | 恒为 `running`（能返回响应就说明活着） |
| `database.state` | `not_configured` / `connected` / `unreachable` —— **只有 connected 才是真的连上了** |
| `identity.auth_mode` | `development_identity` = 开发注入（**不是认证**）；`unauthenticated` = 没有身份，受保护接口返回 401 |

## 安全说明（避免误解）

- **仍然没有登录、没有认证。** 当前的"当前用户"来自开发环境注入的固定身份，
  仅 `APP_ENV=development` + `DEV_USER_ENABLED=true` 时可用，非开发环境一律 401。
- 已经具备的是**数据访问层的隔离形态**：仓储方法强制接收 `UserContext`，
  所有 SQL 都带 `user_id` 过滤，越权与他人资源不存在返回相同 404。
  **这不等于系统已完成安全隔离** —— 正式认证、会话管理、越权审计都还没有。
- 因此本阶段**不能**用于存放真实个人数据，也不能部署到公网。
- 上传目录 `var/uploads/` 已加入 `.gitignore`，且**不会**作为公开静态目录暴露。
- 前端不接触任何模型密钥；所有模型调用将在后端完成。
- `ONLINE_MODEL_API_KEY` 只从 `apps/api/.env` 读取，永不进入代码或日志。

## 文档

- 架构规划：[`docs/planning/00-architecture-plan.md`](docs/planning/00-architecture-plan.md)
- 数据模型：[`docs/design/`](docs/design/)
- 决策记录：[`docs/adr/`](docs/adr/)
- 操作手册：[`docs/runbooks/`](docs/runbooks/)
- 检查报告：[`docs/reports/`](docs/reports/)
