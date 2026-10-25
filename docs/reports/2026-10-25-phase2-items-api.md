# Phase 2 交付报告：UserContext、仓储隔离与衣物 CRUD

- 日期：2026-10-25
- 范围：统一用户上下文、强制隔离的 `ItemRepository`、开发身份注入、衣物 CRUD API、跨用户测试
- **不在本阶段**：Agent、LLM 调用、穿搭推荐、图片上传、长期记忆、JWT/OAuth、云端部署、前端业务页面
- 基线：Phase 1 的 `users` / `items` 模型与迁移 `6efff137cb6c`（**本阶段未改动**）

> 结论先说：仓储层与 API 层的隔离形态已经落地并有测试支撑，**但系统仍不具备认证能力**。
> 当前"当前用户"是开发环境注入的固定身份，非开发环境一律 401。
> "仓储隔离测试通过" ≠ "整个系统已完成安全隔离"。

---

## A. 新增与修改的文件

### 新增（10 个源码 + 3 个测试辅助）

| 文件 | 行数 | 职责 |
|---|---:|---|
| `app/core/user_context.py` | 59 | `UserContext`（不可变）+ `UserOrigin` |
| `app/repositories/item_repository.py` | 180 | 衣物仓储，全部 SQL 带 `user_id` |
| `app/repositories/__init__.py` | 5 | 导出 |
| `app/services/identity.py` | 115 | 身份解析 + 开发用户幂等初始化 |
| `app/services/__init__.py` | 2 | 包声明 |
| `app/api/deps.py` | 68 | 会话 / 身份 / 仓储三个依赖 |
| `app/api/v1/schemas/item.py` | 115 | `ItemCreate` / `ItemUpdate` / `ItemRead` / `ItemListResponse` |
| `app/api/v1/schemas/__init__.py` | 5 | 导出 |
| `app/api/v1/routes/items.py` | 118 | 5 个 CRUD 路由 |
| `tests/factories.py` | 27 | `make_user` / `make_context` |
| `tests/test_user_context.py` | 198 | 18 项 |
| `tests/test_item_repository.py` | 226 | 21 项 |
| `tests/test_items_api.py` | 287 | 36 项 |

### 修改

| 文件 | 改动 | 是否影响行为 |
|---|---|---|
| `app/core/config.py` | 新增 `dev_user_enabled` / `dev_user_public_id` / `dev_user_display_name`；`development_identity_allowed`、`auth_mode`；生产环境启用开发身份 → 构造期 `ValidationError` | 是（新增能力） |
| `app/core/errors.py` | 新增 `AuthenticationRequired`(401) / `NotFoundError`(404) / `DatabaseUnavailable`(503) | 是（新增分支） |
| `app/api/v1/router.py` | 挂载 `items.router` | 是 |
| `app/api/v1/routes/health.py` | `/health` 增加 `identity` 段 | 是（新增字段，见下） |
| `app/main.py` | 启动横幅打印身份模式（开发身份用 WARNING）；OpenAPI 描述更新 | 否（日志/文档） |
| `tests/conftest.py` | 默认关闭开发身份；新增 `api_client`、`dev_user` 夹具 | 是（测试环境） |
| `tests/test_health.py` | 精确键集合断言补上 `identity`；新增身份模式断言 | 是（测试） |
| `app/models/item.py`、`app/models/user.py` | ruff `UP037` 自动修复：`Mapped["User"]` → `Mapped[User]`（`from __future__ import annotations` 下等价） | **否**（无 schema 变化，`alembic check` 已复核） |
| `.env.example` | 新增「开发身份（不是认证）」配置段 | 否 |
| `README.md` | 新增开发身份说明、衣物 API 表、测试隔离说明、安全免责更新 | 否 |
| `apps/api/.env`（本地，已 git 忽略） | 追加 `DEV_USER_*` 三行 + 修正 Phase 0 过期注释 | 是（本地运行） |

**未改动**：`users` / `items` 模型字段、`alembic.ini`、任何迁移文件、数据库结构。

### 接口契约的唯一破坏性变化

`/health` 的响应**多了一个顶级字段 `identity`**。原本 `test_health.py` 用的是
`set(body) == {...}` 精确断言，因此我把 `identity` 加进了期望集合 —— 这是契约变更的
显式登记，不是为了让测试通过而放宽断言。若前端有严格解析，需要同步。

---

## B. UserContext 与开发身份注入

### 上下文对象

```python
@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: int                 # 内部主键，仓储隔离依据
    public_id: uuid.UUID         # 对外标识，不暴露自增顺序
    origin: UserOrigin           # development_identity | authenticated
```

- `frozen=True`：构造后不可改，杜绝"中途换用户"。
- `__post_init__` 校验 `user_id` 为正整数（且排除 `bool`）、`public_id` 为 `UUID`。
- `origin` 是**审计标记，不是授权依据**；当前实际只可能取 `development_identity`。

### 注入链路

```
请求 → get_db_session（Session）
     → get_user_context（resolve_user_context → UserContext）
     → get_item_repository（ItemRepository(session, ctx)）
     → 路由
```

路由签名里只有 `payload` / `item_id` / `repo`，**没有 session、没有 user_id**。

### 四道"客户端无法指定身份"的防线

1. **请求体**：`ItemCreate` / `ItemUpdate` 用 `extra="forbid"`，出现 `user_id` 直接 422。
2. **查询参数**：`get_user_context` 完全不读 `request`，`?user_id=` 只是被忽略的噪声（有测试）。
3. **请求头**：同上，`X-User-Id` 无效（有测试）。
4. **仓储 API 形状**：`create_item()` 签名里没有 `user_id` 形参，传了就 `TypeError`。

### 环境判定（三条件同时满足才给身份）

```python
development_identity_allowed = (
    app_env is development and dev_user_enabled and bool(dev_user_public_id)
)
```

| 场景 | 结果 |
|---|---|
| `development` + `enabled=true` + 合法 UUID | 使用开发身份 |
| `development` + `enabled=false` | **401** |
| `staging` + `enabled=true` | **401**（只有 development 才允许） |
| `production` + `enabled=true` | **启动失败**（`ValidationError`，fail-fast） |
| `production` + `enabled=false` | **401** |

生产环境那条刻意做成"构造 Settings 就抛错"，而不是运行期静默 401 ——
否则一个配置失误就能让线上以固定用户身份读写全部数据。

### 开发用户的创建是受控且幂等的

按 `public_id` 查；不存在则 `INSERT ... ON CONFLICT (public_id) DO NOTHING` 再查一次。

- 依赖 `users.public_id` 的 UNIQUE 约束，并发下也只会有一条；
- 创建时打 **WARNING** 日志（"身份被凭空创建"必须显眼）；
- 有测试断言连续解析两次只得到同一个 `user_id`、库里只有 1 条。

### 替换成正式认证时改哪里

只改 `get_user_context`：改成"校验会话/JWT → 构造 `UserContext(origin=authenticated)`"。
仓储层、路由、schema 均无需改动。这是本阶段刻意保留的唯一边界。

---

## C. ItemRepository 的数据隔离策略

**隔离由构造决定，不由每个方法自觉决定。**

```python
def __init__(self, session: Session, ctx: UserContext) -> None:
    if not isinstance(ctx, UserContext):
        raise TypeError("ItemRepository 必须接收 UserContext 实例")
```

| 方法 | SQL 形态 | 越权时 |
|---|---|---|
| `list_items` | `SELECT ... WHERE user_id = :ctx` | 只返回自己的 |
| `count_items` | `SELECT count(*) WHERE user_id = :ctx` | 只数自己的 |
| `get_item` | `SELECT ... WHERE user_id = :ctx AND id = :id` | `None` |
| `create_item` | `INSERT ... user_id = :ctx`（无 user_id 入参） | 不可能 |
| `update_item` | `UPDATE ... WHERE user_id = :ctx AND id = :id` | `rowcount=0` → `None` |
| `delete_item` | `DELETE ... WHERE user_id = :ctx AND id = :id` | `rowcount=0` → `False` |

### 三个刻意的设计选择

1. **不做"先查再判断"**。UPDATE/DELETE 的 WHERE 直接带 `user_id`，
   越权与不存在在 SQL 层就合并成 `rowcount=0`。没有"先取出来、再决定是否允许"的
   时间窗，也就不存在据此推断资源存在性的路径。
2. **不暴露 session**。`__slots__ = ("_ctx", "_session")`，无 `session` 属性
   （有测试断言 `not hasattr(repo, "session")`），调用方无法绕过过滤自行拼 SQL。
3. **`_UNSET` 哨兵**。用 `_UNSET` 而非 `None` 表示"未提供"，
   才能区分「不修改颜色」与「把颜色清空」。

### 事务语义（实测得出，写进了代码注释）

- 写方法内部 `commit()`，把一次操作当工作单元；
- 若 Session 由调用方加入外层事务，`commit()` **只释放 SAVEPOINT**，外层仍在
  → 这是测试能用"外层事务 + 最终 rollback"隔离 API 写入的前提；
- 但 `rollback()` 会**连带撤掉外层事务**（已实测）。
  因此只在真正的 `SQLAlchemyError` 时才回滚；**"更新命中 0 行"这种正常分支不 rollback**。

> 这一条是本次开发中唯一被测试抓出来的实现缺陷：最初我在 0 行分支调用了 `rollback()`，
> 导致同 Session 上后续读取报 `ObjectDeletedError`。已修正并在 docstring 里写明原因。

---

## D. CRUD API

| 方法 | 路径 | 成功 | 失败 |
|---|---|---|---|
| POST | `/api/v1/items` | **201** + `ItemRead` | 422（校验）/ 401（无身份） |
| GET | `/api/v1/items` | **200** + `{items,total,limit,offset}` | 422（limit 越界）/ 401 |
| GET | `/api/v1/items/{id}` | **200** + `ItemRead` | **404** / 401 |
| PATCH | `/api/v1/items/{id}` | **200** + `ItemRead` | **404** / 422 / 401 |
| DELETE | `/api/v1/items/{id}` | **204**，空 body | **404** / 401 |

### 请求字段

| 字段 | 创建 | 更新 | 约束 |
|---|---|---|---|
| `name` | 必填 | 可省略 | 去首尾空白后长度 1–120；全空白 422；显式 `null` 422 |
| `category` | 必填 | 可省略 | `ItemCategory` 枚枚举，7 个合法值；`"TOP"` / `"上装"` / `""` 全 422 |
| `color` | 可空 | 可清空 | ≤32；空串归一为 `null` |
| `image_ref` | 可空 | 可清空 | ≤512；**只存引用，不提供上传** |
| `user_id` / `id` / `public_id` / `created_at` / `updated_at` | — | — | 一律 **422**（`extra="forbid"`） |

### 响应字段

`{id, name, category, color, image_ref, created_at, updated_at}` —— **不含 `user_id`**：
调用方无需知道归属，暴露它只会给越权探测提供线索。

### 错误码约定

| HTTP | `error.code` | 触发 |
|---|---|---|
| 401 | `authentication_required` | 非开发环境 / 开发身份未开启 |
| 404 | `item_not_found` | 不存在 **或** 不属于当前用户（**同一条错误**） |
| 422 | `validation_error` | 字段非法、多余字段、`limit` 越界 |
| 503 | `database_unavailable` | `DATABASE_URL` 为空 |

响应体统一为 `{"error": {code, message, details, request_id}}`；
500 只回 `internal_error`，堆栈只进日志。

### 为什么是 404 而不是 403

403 等于告诉攻击者"这个 id 存在，只是不属于你"，可用来枚举他人资源。
有专门测试 `test_missing_item_404_is_indistinguishable_from_forbidden`：
把两次响应的 `request_id` 抹掉后断言 **JSON 完全相等**。

---

## E. 测试：命令与实际结果

```bash
./.venv/Scripts/python.exe -m pytest apps/api/tests        # 104 passed in 5.68s
./.venv/Scripts/python.exe -m ruff check apps/api scripts  # All checks passed!
cd apps/api && uv run alembic check                        # No new upgrade operations detected.
cd apps/api && uv run alembic current                      # 6efff137cb6c (head)
```

| 测试文件 | 数量 | 覆盖 |
|---|---:|---|
| `test_health.py` | 10 | 含新增的身份模式断言 |
| `test_config.py` | 5 | 原有 |
| `test_model_registry.py` | 5 | 原有 |
| `test_data_isolation.py` | 9 | 原有（数据库约束层） |
| `test_user_context.py` | **18** | 上下文不可变/校验、环境矩阵、生产 fail-fast、幂等、参数注入无效 |
| `test_item_repository.py` | **21** | 构造校验、无 `user_id` 形参、list/get/update/delete 全维度越权、清空字段、分页 |
| `test_items_api.py` | **36** | CRUD 正常路径、非法输入、`user_id` 注入、404 不可区分、401、错误卫生 |
| **合计** | **104** | 由 28 增至 104（+76） |

**全部真实执行，零 skip。** 数据库用例确认走的是真实 PostgreSQL
（先跑 `alembic upgrade head`，`db_engine` 夹具检测到表缺失时会 skip，
本次没有任何 skip，说明表存在且用例真的跑了）。

### 验证"测试没有污染数据库"

```
测试后 users/items 行数 = (0, 0)
alembic 版本 = 6efff137cb6c
```
76 个新用例里大量是写操作，跑完库里仍是 0 行 → 外层事务回滚策略未被破坏。

### 未覆盖的场景（明确列出）

1. **并发/竞态**：两个请求同时创建开发用户、或同时 PATCH 同一件衣物，没有测试。
2. **`image_ref` 的真实性**：只校验长度，不校验"该引用是否真实存在"（上传功能未做）。
3. **数据库故障下的 API 行为**：`DatabaseUnavailable` 分支只有构造层面覆盖，
   没有测试"运行中数据库断开"。
4. **500 错误的密钥卫生**：只对 404/422 断言了无泄露；未构造真实 500 来验证。
5. **多进程/多 worker**：`uvicorn --workers N` 下的行为未测。
6. **鉴权层**：没有认证，因此也没有"令牌过期/伪造/重放"这类测试。

---

## F. 安全风险与未完成项

### F-1【最高优先级】仍无认证，开发身份等于"谁都能以同一用户操作"

只要 `APP_ENV=development` 且开关打开，任何能访问 8000 端口的进程都是同一个用户。
当前服务只监听 `127.0.0.1`，风险可控；**一旦改成 `0.0.0.0` 或部署到公网，就是全部数据裸奔**。

缓解已就位：生产环境启用即拒绝启动、`/health` 如实报告 `auth_mode`、启动日志 WARNING。

### F-2【结构性】隔离只到"仓储 + 输入形状"，没有授权层

已做：仓储强制 `user_id`、schema 禁止 `user_id`、越权统一 404。
未做：**身份真实性校验**（现在身份是自己声明的配置）、**操作审计**、**越权告警**。

### F-3 开发用户会被自动创建

若把 `DEV_USER_PUBLIC_ID` 改错，会静默创建一个全新空用户（老用户的数据还在，但看不到）。
缓解：创建时打 WARNING。若要完全避免，可加"禁止自动创建"开关 —— 本阶段刻意不加，保持简单。

### F-4 测试策略的隐性依赖

API 测试能复用"外层事务 + rollback"，依赖 `Session.join_transaction_mode` 的默认值
（`conditional_savepoint`）。若将来显式改成 `rollback_only` 或 `control_fully`，
`commit()` 的语义会变，隔离会失效且**测试不会报错**。已在 README 记录。

### F-5 分页性能

`count_items()` 每次请求都 `count(*)`。万级以内无感，数据量上来后需要改成估算或缓存。

### F-6 阶段遗留

- `var/secrets/` 两个密码文件仍是明文（前两阶段就提出，仍未处理）。
- Git 仍 **0 次提交**（`user.name/user.email` 未配置），89 个待跟踪文件。
- Ollama 未启动；视觉能力缺失问题未解决（模型无 projector 层）。

---

## G. Git diff 摘要与 schema 变化

```
待提交文件：89（全部为 ?? 未跟踪，仓库尚无任何 commit）
敏感文件进入待提交：无（.env / var/secrets/* 均被忽略，已复查）
提交历史：0 commits（main 分支，无历史可被破坏）
```

**数据库 schema：无变化。**

- 未新增迁移文件（`migrations/versions/` 仍只有 `6efff137cb6c`）；
- `alembic check` → `No new upgrade operations detected`；
- `alembic current` → `6efff137cb6c (head)`；
- 模型文件的唯一改动是 ruff 自动去掉了类型注解的引号（`Mapped["User"]` → `Mapped[User]`），
  `from __future__ import annotations` 生效时二者完全等价，不产生 DDL。

**因此：本阶段不需要任何迁移。**

### 运行期数据变化

| 对象 | 变化 |
|---|---|
| `users` | 新增 1 条开发用户（`public_id=8f3a1c2e-…`，`display_name=本地开发用户`）—— 这是运行应用时按设计创建的，属预期 |
| `items` | 0 条（端到端验证时创建的 1 条已通过 API 自己删除，`id=313`） |
| 序列 | `items.id` 因测试回滚消耗了序号，故首条真实记录 id 为 313，非 1（序列不回滚是 PostgreSQL 正常行为） |

---

## 附：端到端实测记录（真实服务，非测试覆盖）

```
GET  /health            → 200  database=connected 3.0ms  identity.auth_mode=development_identity
POST /api/v1/items      → 201  {"id":313,"name":"白色牛津纺衬衫","category":"top","color":"白色"}
GET  /api/v1/items      → 200  total=1
GET  /api/v1/items/313  → 200
PATCH /api/v1/items/313 → 200  name/color 已改，updated_at 已更新，category 未动
GET  /api/v1/items/999999999 → 404  {"code":"item_not_found"}
POST body 带 user_id    → 422  extra_forbidden @ body.user_id
POST category=spacesuit → 422  enum
POST name="   "         → 422  string_too_short
DELETE /api/v1/items/313 → 204 空 body
GET  /api/v1/items/313  → 404
DELETE 再来一次         → 404
GET  /docs              → 200
OpenAPI 路径            → 5 个 /api/v1/items* + 2 个 health（无 agent/recommend 类接口）
```

服务验证后已停止，8000 端口已释放。

---

## 下一步建议（按优先级）

1. **配置 Git 身份并做首次提交**（89 个文件还没有任何版本历史，这是当前最大风险）。
2. **最小认证**：签发/校验会话，把 `get_user_context` 换成真实实现；
   加"令牌无效 → 401"与"两用户令牌互不可用"的测试。
3. 越权审计日志：404 命中他人资源时记录 `request_id + public_id`（不记录被访问的 id）。
4. 图片上传前先定存储方案与隐私裁剪策略，再接 `image_ref` 校验。
5. `docs/design/` 补一份 API 契约说明，或直接由 OpenAPI 生成 TS 类型到 `packages/contracts`。
