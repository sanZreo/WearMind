# Phase 3：正式身份认证与授权 —— 方案比较与威胁模型

- 日期：2026-10-25
- 状态：**设计稿，等待审核。尚未编写任何认证代码，未新增依赖，未建表，未改接口。**
- 依据：`docs/planning/WearMind-Project-Roadmap.md` §Phase 3、`docs/planning/00-architecture-plan.md` B.7 Q1 与 G.1 第 5 项
- 前置阶段：Phase 2（`UserContext` / `ItemRepository` / 开发身份注入 / 衣物 CRUD，104 项测试）

---

## 0. 一句话结论

> **推荐：服务端有状态会话（不可伪造的随机令牌，放 `HttpOnly` Cookie）+ 邮箱密码（Argon2id）+ 数据库会话表 + CSRF 双重防御。**
>
> 不使用 JWT 作为浏览器侧会话载体。理由是：本项目的第一个硬需求是**撤销**（退出登录、改密后踢掉旧会话、账号删除），而 JWT 的自包含特性让撤销必须借助额外的黑名单表 —— 那就等于既写了一张会话表、又保留了令牌泄漏无法撤回的风险，复杂度换不到收益。
>
> 第三阶段只做「邮箱 + 密码 + 会话」，**不做**找回密码、邮箱验证、OAuth 登录。这些留到有邮件通道或明确需求之后。

---

## 1. 现状基线（实测，非推测）

改代码前必须先承认现状，否则容易把「已有」当成「已够用」。

| 项 | 现状 | 位置 | 判定 |
|---|---|---|---|
| 身份载体 | `UserContext`（`frozen=True, slots=True`），含 `user_id` / `public_id` / `origin` | `apps/api/app/core/user_context.py` | ✅ 可直接复用，认证只需换解析来源 |
| 身份来源 | 只有 `development_identity`，需 `APP_ENV=development` + `DEV_USER_ENABLED` + `DEV_USER_PUBLIC_ID` 三者同时成立 | `app/core/config.py::development_identity_allowed` | ⚠️ **不是认证** |
| 生产环境防护 | `APP_ENV=production` 且 `DEV_USER_ENABLED=true` → `Settings` 构造期抛 `ValueError`，启动即失败 | `app/core/config.py::_guard_development_identity` | ✅ 已有，Phase 3 应保留并加回归测试 |
| 身份解析入口 | `resolve_user_context(session)`，唯一 | `app/services/identity.py` | ✅ 只有一处要替换 |
| 依赖注入 | `get_user_context` → `UserContextDep`；仓储 `get_item_repository` | `app/api/deps.py` | ✅ 替换点已隔离 |
| 数据隔离 | `ItemRepository` 所有查询强制带 `user_id`；跨用户访问返回 404 而非 403 | `app/repositories/item_repository.py` | ✅ Phase 2 已建好第一道防线 |
| `users` 表 | `id` / `public_id` / `display_name` / 时间戳。**无 email、无密码、无令牌字段** | `app/models/user.py` | ❌ 需扩表或新增子表 |
| 认证相关依赖 | **零**。`pyproject.toml` 只有 fastapi / uvicorn / pydantic / pydantic-settings / sqlalchemy / alembic / psycopg | `apps/api/pyproject.toml` | ❌ 需引入密码哈希库 |
| 错误响应 | 统一 `AppError` → `{code, message, details}`；已有 `AuthenticationRequired`(401, `authentication_required`) | `app/core/errors.py` | ✅ 复用，补 `invalid_credentials` |
| 未认证行为 | `development_identity_allowed=False` 时抛 `AuthenticationRequired` → 401，**不会退化成默认用户** | `app/services/identity.py` | ✅ 已符合"未登录不能访问" |

**结论：Phase 3 不需要动 `ItemRepository`、不需要动 `items` 路由、不需要动 `UserContext` 的语义。**
只需要：① 新增凭据与会话表；② 新增认证路由；③ 把 `get_user_context` 的内部实现从"读配置"换成"读会话"。

### 1.1 当前部署形态对 Cookie 的影响（容易踩）

| 环境 | 前端 | 后端 | 站点关系 | Cookie 可用性 |
|---|---|---|---|---|
| 本地开发 | `http://localhost:3000` | `http://localhost:8000` | **同站**（`localhost`），**跨源**（端口不同） | Cookie 可写；但必须 `credentials: 'include'` + CORS `allow_credentials=True` + 精确 origin（不能用 `*`） |
| 生产（建议） | `https://www.example.com` | `https://api.example.com` | **同站**（eTLD+1 相同），**跨源** | 同上，且必须 HTTPS + `Secure` |

> 关键判断：**"跨源"不等于"跨站"**。`SameSite=Lax` 依赖的是"站"（eTLD+1），所以当前 localhost:3000→8000 与未来的 www↔api 都能正常工作。
> 但这同时意味着：**同一 eTLD+1 下的兄弟子域（例如被攻陷的 `blog.example.com`）属于"同站"**，`SameSite=Lax` 拦不住它发起的 CSRF。因此不能只靠 `SameSite` 防 CSRF，必须叠加 `Origin` 校验 —— 见 §9。

---

## 2. 攻击面与信任边界

```
┌──────────────┐  ①  浏览器  ┌────────────────┐  ②   HTTP   ┌─────────────────┐
│  用户浏览器   │ ─────────→ │ Next.js 前端    │ ──────────→ │ FastAPI 后端     │
│ (可能被 XSS)  │            │ (不可信渲染层)   │  Cookie+TLS │ (唯一权威)       │
└──────────────┘            └────────────────┘             └────────┬────────┘
       ▲                                                              │ ③
       │ ⓪ 攻击者控制的页面 / 恶意扩展 / 同站子域                      │
       │                                                              ▼
       │                                                    ┌─────────────────┐
       └────────── 伪造请求（CSRF）──────────────────────────│ PostgreSQL      │
                                                            │ users / sessions│
                                                            └─────────────────┘
```

| 边界 | 信任假设 | 违反后果 |
|---|---|---|
| ⓪ → ① 浏览器环境 | **不可信**。可能被 XSS、恶意扩展、同站子域污染 | 能读到的令牌即被盗 |
| ① → ② 网络 | 生产必须 TLS；本地可降级 | 中间人窃取 Cookie |
| ② 前端 | **只做渲染，不做授权判断**。前端隐藏按钮不算权限控制 | 隐藏 UI 后直接调 API 即可越权 |
| ② → ③ 数据库 | 可信。会话与凭据的**唯一**权威 | 库被读 = 全部会话失效（因此令牌只存哈希） |

**铁律（延续 Phase 2 的三条硬性架构规则）**：`UserContext` 只能由后端从**服务端可验证的凭据**构造；任何来自请求体、查询参数、普通请求头的用户标识一律不采信。

---

## 3. 威胁模型

### 3.1 资产

| 编号 | 资产 | 敏感度 | 落在哪 |
|---|---|---|---|
| A1 | 用户衣物数据（名称、品类、颜色、将来的图片） | 高（个人生活信息） | `items` 表 + 将来的文件存储 |
| A2 | 用户身份（邮箱、`public_id`、展示名） | 中高（可用于撞库/社工） | `users` / `auth_identities` |
| A3 | 密码 | **最高**（用户往往复用） | 只以 Argon2id 哈希存在 |
| A4 | 会话令牌 | 高（持有即等于登录态） | Cookie（明文仅存于客户端）+ 数据库（只存哈希） |
| A5 | 数据库连接串、模型 API Key | 高 | `apps/api/.env`（已忽略，不入库） |
| A6 | 服务可用性 | 中 | 后端进程 / PostgreSQL |

### 3.2 攻击者

| 编号 | 攻击者 | 能力 | 最关心的目标 |
|---|---|---|---|
| T1 | 未认证的互联网用户 | 可任意调用公开接口 | 枚举账号、撞库、抢注 |
| T2 | 已注册的普通用户 | 有合法会话 | **横向越权**：读别人的衣物（最高优先级） |
| T3 | 同站子域/供应链被攻陷 | 能发起同站请求 | CSRF、窃取 Cookie |
| T4 | 能执行 XSS 的攻击者 | 能在页面内跑 JS | 读 `localStorage`、伪造请求 |
| T5 | 拿到数据库快照的人 | 离线读全库 | 还原密码、复用会话 |
| T6 | 本机其他进程/误配置 | 读 `.env`、改环境变量 | 用开发身份绕过认证 |
| T7 | 日志/报错泄漏 | 读日志、看错误页 | 从日志里捞令牌或密码 |

### 3.3 STRIDE 分解

| 类别 | 本项目的具体形态 | 对策（编号对应 §14 任务） |
|---|---|---|
| **S**poofing 冒充 | 伪造 Cookie；猜令牌；用开发身份冒充 | 256-bit 随机令牌；只存哈希；开发身份三重环境门禁（T2, T8） |
| **T**ampering 篡改 | 改 `user_id` / `public_id` / `item_id` 提权 | 身份只从会话推导；仓储强制 `WHERE user_id=?`（已实现）；越权返回 404（T7） |
| **R**epudiation 抵赖 | 说不清"谁在什么时候登录/退出" | 结构化审计事件，只记事件与 `public_id`，不记凭据（T9） |
| **I**nformation disclosure 信息泄漏 | 登录报错区分"账号不存在/密码错"；日志打印令牌；响应体回显密码 | 统一 `401 invalid_credentials`；日志脱敏（已有 `***` 掩码实践）；Pydantic `extra="forbid"` + 响应模型不含敏感字段（T5, T9） |
| **D**enial of service 拒绝服务 | 暴力破解登录；超长密码打爆 Argon2 | 登录限流 + 指数退避；密码长度上限 128 字符（T6） |
| **E**levation of privilege 提权 | 会话固定；改密后旧会话仍有效；`origin` 被伪造成 `authenticated` | 登录时**换发新令牌**；改密撤销其他会话；`origin` 由服务端赋值（T3, T8） |

### 3.4 关键滥用场景（逐条给结论）

| # | 场景 | 若不做会怎样 | 对策 | 残余风险 |
|---|---|---|---|---|
| U1 | 攻击者拿 A 的 `item_id` 调 `GET /items/{id}` | 读到 A 的衣物 | 仓储 `WHERE id=? AND user_id=?`，0 行 → 404。**已实现** | 无（除非仓储被绕过） |
| U2 | 攻击者在请求体里塞 `user_id` 指定别人 | 直接写进别人的衣柜 | `ItemCreate` `extra="forbid"` + 仓储签名不收 `user_id`。**已实现** | 无 |
| U3 | 攻击者构造 `Cookie: wm_session=<猜的>` | 猜中即登录 | 32 字节 `secrets.token_bytes` + 只存 SHA-256；猜中概率可忽略 | 无 |
| U4 | 攻击者从库里拿到 `sessions` 表 | 直接当令牌用 | 库存的是 **SHA-256 哈希**，不是令牌本身 | 库被读仍需穷举原像，不可行 |
| U5 | 恶意站点诱导用户点击，发起 `POST /items` | 以用户身份建数据 | `SameSite=Lax`（跨站 POST 不带 Cookie）+ `Origin` 白名单校验 + CSRF double-submit | 老浏览器忽略 `SameSite` → 靠 `Origin` 兜住；因此 `Origin` 是**必需**而非可选 |
| U6 | 同站子域（`blog.example.com`）发起 CSRF | `SameSite` 不管用（同站） | `Origin` 必须精确匹配白名单；不带 `Origin` 的写请求直接拒绝 | 若攻击者能控制 `Origin`（不可能，浏览器强制） |
| U7 | XSS 读走令牌 | 长期冒充 | `HttpOnly` 让 JS 读不到 Cookie；`HttpOnly` 是**本方案的核心收益** | XSS 仍可"代用户发请求"；防线是 CSP 与不引入不可信脚本，属 Phase 6 硬化 |
| U8 | 撞库：拿别的站泄露的邮箱密码来试 | 账号被接管 | Argon2id 慢哈希 + 登录限流 + 统一错误（不告诉攻击者"这个邮箱存在"） | 无法根除，只能降速 |
| U9 | 攻击者遍历邮箱判断谁注册过 | 拿到用户名单 | 登录失败统一 `401`；注册冲突的处理见 §18 第 4 项（有取舍） | 注册接口天然会泄漏存在性，需靠限流压制 |
| U10 | 登录前先在受害者浏览器里塞一个固定会话 ID | 会话固定攻击 | 登录成功一律**新建**会话、不沿用任何客户端提供的会话 ID | 无 |
| U11 | 改密后旧设备仍在线 | 被盗账号无法收回 | 改密时撤销该用户**其他所有**会话 | 当前设备保留，需在响应里明确告知 |
| U12 | 误把 `APP_ENV` 配成 `development` 就上线 | 开发身份直接放行 | `Settings` 构造期拒绝 + 启动日志打印 `auth_mode` + 生产检查清单 | 人为配错仍可能，靠部署检查兜 |
| U13 | 日志里打出 `Authorization` / Cookie / 密码 | 日志成为凭据仓库 | 只记 `public_id` 与会话 `id`（整数），永不记令牌；请求日志中间件显式跳过 `cookie` / `set-cookie` | 无 |
| U14 | 账号删除后数据残留 | 违反"删除账号即清除衣物"的设计承诺 | `users` → `items` `ON DELETE CASCADE`（已实现）；`sessions` / `auth_identities` 同样 `CASCADE` | 文件存储需在 Phase 4 单独处理 |
| U15 | 用户上传的衣物图片被发到第三方视觉模型 | 隐私外泄 | 属 Phase 4/6 范围；本阶段只在文档立规：**未经用户明示同意不得外传** | — |

---

## 4. 方案比较

### 4.1 候选

| 代号 | 方案 | 令牌形态 | 状态存放 |
|---|---|---|---|
| **A** | 服务端会话 + 不透明随机令牌（Cookie） | 256-bit 随机串 | 数据库 `sessions` 表 |
| **B** | JWT 放 `HttpOnly` Cookie | 自包含签名令牌 | 无状态（可选黑名单） |
| **C** | JWT 放 `Authorization: Bearer`（前端存 `localStorage`） | 自包含签名令牌 | 无状态 |
| **D** | 第三方 OAuth / OIDC（GitHub、Google） | 由 IdP 签发 | 无状态或会话 |
| **E** | Passkey / WebAuthn（无密码） | 挑战-响应 | 公钥存库 |

### 4.2 评分表

评分：★★★ 优 / ★★ 可接受 / ★ 差。「权重」按本项目实际需求给定（撤销与 XSS 权重最高）。

| 维度 | 权重 | A 服务端会话 | B JWT-Cookie | C JWT-localStorage | D OAuth | E Passkey |
|---|---|---|---|---|---|---|
| 即时撤销（退出/改密/删号） | **高** | ★★★ 删一行即可 | ★ 需黑名单表，且要额外查询 | ★ 同 B | ★★ 依赖 IdP，本地仍需会话 | ★★★ |
| XSS 下令牌可被 JS 读取 | **高** | ★★★ `HttpOnly` 读不到 | ★★★ `HttpOnly` | ★ `localStorage` 直接可读 | ★★ | ★★★ |
| CSRF 风险 | 高 | ★★ 需 `SameSite`+`Origin`+token | ★★ 同 A | ★★★ 无（不用 Cookie） | ★★ | ★★ |
| 实现复杂度 | 中 | ★★★ 一张表 + 一次 SELECT | ★★ 要管签名/算法/时钟/刷新 | ★★ 同 B + 前端存储决策 | ★ 要接 IdP、回调、账号绑定 | ★ 挑战流程 + 设备兼容 |
| 依赖与密钥管理 | 中 | ★★★ **零密钥**（随机串不需签名） | ★★ 要管 `JWT_SECRET` 轮换 | ★★ 同 B | ★★ client_secret | ★★ |
| 多设备/多端管理 | 中 | ★★★ 天然按会话行管理 | ★ 只能靠 `jti` 黑名单曲线实现 | ★ 同 B | ★★ | ★★ |
| 水平扩展（无状态） | 低 | ★★ 每次请求 1 次索引查询 | ★★★ | ★★★ | ★★ | ★★ |
| 离线/断网可用 | 低 | ★ 需查库 | ★★★ | ★★★ | ★ | ★ |
| 与现有代码契合度 | 中 | ★★★ 只换 `get_user_context` | ★★ 同 | ★★ | ★ 需新增账号绑定表 | ★ 需 HTTPS 强制 |
| 用户可用性（本地单机） | 低 | ★★★ 邮箱密码即可 | ★★★ | ★★★ | ★★ 要跳转外部 | ★ 要生物识别设备 |
| **加权结论** | | **✅ 选 A** | 次选 | ❌ 排除 | 后续可选 | 后续可选 |

### 4.3 逐项分析（只写决定性理由）

**为什么不用 JWT（B/C）**

1. **第一个硬需求就是撤销。** 路线图验收项明确要求「登录、退出、过期、撤销」都有测试。JWT 一旦签发，在 `exp` 前始终有效。要支持"退出即失效""改密踢掉旧会话""账号删除立即生效"，就必须维护一张 `revoked_jti` 表或 `token_version` 字段 —— **照样要查库**，那 JWT 唯一的优势（无状态）就消失了，反而多背一套签名/算法/时钟偏移的坑。
2. **多一个密钥就多一个泄漏面。** `JWT_SECRET` 要生成、要轮换、要保证所有实例一致；轮换时旧令牌全废。方案 A **压根没有签名密钥** —— 令牌本身就是高熵随机数，安全性来自"不可猜"而非"不可伪造"。
3. **`alg: none` / 算法混淆**是 JWT 的经典事故源，虽然成熟库已默认规避，但少一个可踩的坑就是收益。
4. **C 方案直接排除**：`localStorage` 里的令牌任何 XSS 都能读走，且无法用 `HttpOnly` 保护。对"存用户私密衣物照片"的应用，这是不可接受的基线。

**为什么不用 OAuth/OIDC（D）**

技术上更"现代"，但本项目当前是**单用户本地 MVP**：引入 GitHub/Google 登录意味着要注册 OAuth App、处理回调域名、做账号绑定与解绑、处理 IdP 不可用时的降级 —— 全是当前不需要的复杂度，且**没有解决授权问题**（OAuth 只回答"你是谁"，不回答"这件衣服是不是你的"，后者仍靠仓储隔离）。

保留扩展位：数据模型上用 `auth_identities(provider, subject)` 多行设计，将来加 `github` / `google` 只是插入新行，不动 `users` 与 `items`。

**为什么不用 Passkey（E）**

体验最好、抗钓鱼最强，但要求 HTTPS（本地开发要绕）、要求设备支持、且丢失设备后的恢复流程复杂。适合作为**后续增强**，不适合作为第一个认证实现。

---

## 5. 推荐方案（方案 A 的具体形态）

```
登录 POST /auth/login
  ├─ 校验 Origin 在白名单
  ├─ 限流（IP + 账号）
  ├─ 查 auth_identities(provider='password', subject=normalized_email)
  ├─ 不存在 → 仍执行一次假哈希校验（等时），返回统一 401
  ├─ Argon2id 校验失败 → 统一 401（不区分"无此账号"与"密码错"）
  ├─ 成功 → 新建 session（32B 随机令牌），存 SHA-256 哈希
  └─ Set-Cookie: wm_session=<raw>; HttpOnly; Path=/; SameSite=Lax; [Secure]
       + Set-Cookie: wm_csrf=<random>; Path=/; SameSite=Lax   （非 HttpOnly，供前端读取回填）

后续请求
  Cookie → SHA-256 → 查 sessions.token_hash（唯一索引）
    ├─ 无此哈希 / 已撤销 / 已过绝对期 / 已过空闲期 → 401（并清 Cookie）
    └─ 命中 → 更新 last_seen_at（滑动续期，节流写）→ 构造 UserContext(origin=authenticated)
```

**选它的三条决定性理由**

1. **撤销是一行 `UPDATE ... SET revoked_at = now()`**，没有"令牌还在有效期内但我已踢人"的窗口。
2. **没有签名密钥**，少一个必须轮换、必须保密的配置项。
3. **改动面最小**：`UserContext` / `ItemRepository` / `items` 路由全部不动，只替换 `get_user_context` 的实现。

---

## 6. 数据模型（设计，未迁移）

### 6.1 为什么不把 `email` / `password_hash` 直接加到 `users`

| 方案 | 优点 | 缺点 |
|---|---|---|
| 直接加列到 `users` | 少一张表、少一次 JOIN | `users` 变成"账号 + 凭据"混合体；将来加 OAuth 时 `password_hash` 对本就用不上密码的用户只能为 `NULL`，语义含糊；一个用户想绑多种登录方式时无处可放 |
| **独立 `auth_identities`（推荐）** | 一个用户可挂多条身份（密码 + GitHub + Google）；`secret_hash` 只在 `provider='password'` 时有值；加 provider 只加 CHECK 值 | 多一张表、登录多一次 JOIN（可忽略） |

选独立表。理由与 Phase 1 拒绝把颜色做成枚举一致：**给最可能演化的维度留出结构**。

### 6.2 `auth_identities`

| 字段 | 类型 | 约束 | 理由 |
|---|---|---|---|
| `id` | `BIGINT` | PK, `IDENTITY` | 与 `users` / `items` 一致 |
| `user_id` | `BIGINT` | `NOT NULL`，FK → `users.id` `ON DELETE CASCADE` | 删号即清凭据 |
| `provider` | `VARCHAR(32)` | `NOT NULL`，`CHECK IN ('password','github','google')` | 用 VARCHAR+CHECK 而非原生 ENUM（同 Phase 1 §4 的理由：加值只需改 CHECK） |
| `subject` | `VARCHAR(255)` | `NOT NULL` | provider 内的唯一标识。`password` 时为**规范化后的邮箱**（小写、去空格） |
| `secret_hash` | `VARCHAR(255)` | `NULL` | 仅 `password` 用，存 Argon2id 的 PHC 字符串（自带参数与盐）。其他 provider 为 `NULL` |
| `email_verified` | `BOOLEAN` | `NOT NULL DEFAULT false` | 预留。当前无邮件通道，注册后直接为 `false` 但**不阻塞登录**（见 §18 第 4 项） |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | `NOT NULL` | 同现有表 |

约束与索引：

| 名称 | 定义 | 作用 |
|---|---|---|
| `uq_auth_identities_provider_subject` | `UNIQUE (provider, subject)` | 同一 provider 下标识唯一 = 不能重复注册同一邮箱 |
| `ck_auth_identities_provider_valid` | `provider IN (...)` | 挡住拼写错误 |
| `ck_auth_identities_secret_required` | `provider <> 'password' OR secret_hash IS NOT NULL` | **密码身份必须有哈希**，防止建出"有账号没密码"的不可登录孤儿行 |
| `ix_auth_identities_user_id` | `(user_id)` | 改密时撤销该用户所有会话/查其所有身份 |

> 邮箱是否 `CITEXT`：不引入扩展。统一在应用层 `normalize_email()`（`strip().lower()`）后再写入 `subject`，并把该函数作为唯一入口 —— 否则 `A@x.com` 与 `a@x.com` 会变成两个账号。

### 6.3 `sessions`

| 字段 | 类型 | 约束 | 理由 |
|---|---|---|---|
| `id` | `BIGINT` | PK, `IDENTITY` | 审计与日志里用整数 id，不暴露令牌 |
| `user_id` | `BIGINT` | `NOT NULL`，FK → `users.id` `ON DELETE CASCADE` | 删号即踢下线 |
| `token_hash` | `BYTEA` | `NOT NULL`，**`UNIQUE`** | `SHA-256(原始令牌)`。唯一索引让校验是 O(1)，且库泄漏也拿不到可用令牌 |
| `issued_at` | `TIMESTAMPTZ` | `NOT NULL` | 审计 |
| `last_seen_at` | `TIMESTAMPTZ` | `NOT NULL` | 空闲超时的判据；滑动续期时更新（节流，见 §7） |
| `absolute_expires_at` | `TIMESTAMPTZ` | `NOT NULL` | 硬上限，不因活跃而延长 |
| `revoked_at` | `TIMESTAMPTZ` | `NULL` | 非空即失效。**不做物理删除**，保留作审计 |
| `revoked_reason` | `VARCHAR(32)` | `NULL`，`CHECK IN ('logout','password_change','admin','superseded')` | 区分"用户主动退出"与"被踢"，排障必需 |
| `user_agent` | `VARCHAR(255)` | `NULL` | 截断存储，供"我的登录设备"列表。**不存 IP**（隐私：IP 属个人数据，且 IPv6 前缀即可定位到户） |

索引：

| 名称 | 列 | 用途 |
|---|---|---|
| `uq_sessions_token_hash` | `token_hash` UNIQUE | 每次请求的校验路径 |
| `ix_sessions_user_id_revoked_at` | `(user_id, revoked_at)` | "列出我的活跃会话" / "踢掉该用户所有会话" |

**为什么 `token_hash` 用 `BYTEA` 而非 `VARCHAR`**：`SHA-256` 天然是 32 字节二进制，`BYTEA` 定长、比较更快、也不会出现大小写/编码不一致。用 `hex` 字符串存也可行，但等于把体积翻倍且引入编码歧义。

---

## 7. 令牌与会话生命周期

| 项 | 取值 | 理由 |
|---|---|---|
| 令牌熵 | **256 bit**（`secrets.token_bytes(32)`） | 远超暴力破解可行范围 |
| 传输形态 | `base64url` 无填充（43 字符） | URL 安全、无歧义字符 |
| 是否加前缀 | 建议 `wm_` 前缀 | 便于密钥扫描器（如 GitHub secret scanning）识别；也便于日志脱敏正则锚定 |
| 服务端存储 | `SHA-256(raw)` | 令牌本身是高熵随机数，**不需要** Argon2（那是给低熵密码用的；对 256-bit 随机值用慢哈希只会让每次请求多花几十毫秒，纯浪费） |
| 空闲超时 | **7 天**（`last_seen_at` 起算） | 个人穿搭应用，一周不用才要求重新登录，符合预期 |
| 绝对超时 | **30 天**（`issued_at` 起算） | 硬上限，防止"一直用就一直有效"的无限会话 |
| 滑动续期 | 每次请求若 `now - last_seen_at > 5 分钟` 才 `UPDATE` | 避免每个请求都写库造成写放大 |
| 登录时 | **必定新建会话**，绝不复用客户端送来的任何值 | 防会话固定（U10） |
| 退出 | `revoked_at = now()`, `revoked_reason='logout'` + 清 Cookie | 立即失效 |
| 改密 | 撤销该用户**其他**所有会话 | 被盗后用户能自行收回（U11） |
| 过期/失效响应 | 401 + `Set-Cookie` 清除 | 让前端立即回到未登录态 |
| 令牌轮换 | **不做**每请求轮换 | 会引入并发请求互相踢掉的经典 bug，收益不抵成本 |

---

## 8. 密码存储

| 项 | 决策 | 理由 |
|---|---|---|
| 算法 | **Argon2id**（`argon2-cffi`） | 密码哈希当前最优选（OWASP 推荐）。同时抗 GPU 与侧信道 |
| 参数（起步值） | `time_cost=3`, `memory_cost=64 MiB`, `parallelism=4`, `hash_len=32`, `salt_len=16` | OWASP 的 Argon2id 基线之一。**需在目标机器实测单次耗时**，落在 50–200 ms 之间最合适（太快不安全，太慢则登录接口可被用来打 DoS） |
| 参数可变 | 参数存在 PHC 字符串里，天然自描述 | 将来调参不需要迁移数据：登录成功发现参数过期 → 用新参数重算并更新 |
| 备选（若 `argon2-cffi` 在 Python 3.13 上装不上） | `hashlib.scrypt(n=2**15, r=8, p=1)`，**标准库、零依赖** | 功能上可接受（内存硬），只是调参不如 Argon2id 灵活 |
| 密码策略 | 长度 **≥12**、**≤128**；不做大小写/符号强制；拒绝纯空白 | NIST SP 800-63B：长度优于复杂度规则；上限防 DoS（Argon2 对超长输入也要吃 CPU） |
| 常见弱密码 | 内置一个小型黑名单（如 `password123456`）拒绝 | 不引入几 MB 的字典依赖，只挡最离谱的 |
| 盐 | 由 `argon2-cffi` 自动生成并写入 PHC 串 | 不自己造盐 |
| 明文密码的出现范围 | **只在请求体里出现一次**，不落库、不落日志、不回显、不进异常信息 | 与 Phase 2.5 的凭据纪律一致 |
| 时间侧信道 | 账号不存在时也执行一次**固定的假哈希校验** | 否则"响应快 = 账号不存在"（U9） |

---

## 9. Cookie / CORS / CSRF

### 9.1 Cookie

| 属性 | 会话 Cookie `wm_session` | CSRF Cookie `wm_csrf` |
|---|---|---|
| `HttpOnly` | ✅ **是**（核心收益：XSS 读不到） | ❌ 否（前端必须能读来回填请求头） |
| `Secure` | 生产 ✅；开发（`http://localhost`）可关 | 同左 |
| `SameSite` | `Lax` | `Lax` |
| `Path` | `/` | `/` |
| `Domain` | **不设置**（host-only） | **不设置** |
| `Max-Age` | 与空闲超时一致（7 天） | 同左 |
| 名称（生产） | `__Host-wm_session` | `__Host-wm_csrf` |

> `__Host-` 前缀强制 `Secure` + `Path=/` + 无 `Domain`，浏览器会拒绝不合规的同名 Cookie —— 这是防"子域种 Cookie 覆盖"的低成本加固。开发环境因走 http，使用普通名 `wm_session`。

### 9.2 CORS

| 项 | 取值 | 理由 |
|---|---|---|
| `allow_origins` | **精确白名单**（来自 `CORS_ORIGINS`，已是逗号分隔配置） | 带凭据的请求**禁止** `*`（浏览器也会拒绝） |
| `allow_credentials` | `True` | 否则浏览器不发送/不接收 Cookie |
| `allow_methods` / `allow_headers` | 显式列出（需含 `X-CSRF-Token`） | 不用 `*`，避免放宽过头 |
| 前端 | `fetch(..., { credentials: 'include' })` | 缺失则 Cookie 不会跨源携带 |

### 9.3 CSRF：三层叠加，缺一不可

| 层 | 机制 | 挡住什么 | 挡不住什么 |
|---|---|---|---|
| 1 | `SameSite=Lax` | 跨站 `POST`/`PUT`/`DELETE` 不带 Cookie | 同站子域（U6）；老浏览器 |
| 2 | **`Origin` 校验**（写操作强制） | 同站子域伪造、以及任何来源不明的写请求 | 同源内的 XSS（那已不是 CSRF） |
| 3 | **Double-submit**：`wm_csrf` Cookie 值必须与 `X-CSRF-Token` 头一致（常量时间比较） | 攻击者无法读取 Cookie 值去伪造头（跨源读 Cookie 受同源策略限制） | 同站子域可读到自己种的 Cookie → 所以第 2 层不能省 |

**为什么不只用 `SameSite=Strict`**：`Strict` 会让"从外部链接点进来"的首次请求不带 Cookie，用户会看到"已登录却被弹回登录页"，体验明显变差。`Lax` + `Origin` 是更好的组合。

**允许不带 `Origin` 的情况**：仅同源 `GET` 与非浏览器客户端（如 `curl` 调试）。写操作若 `Origin` 缺失 → **拒绝**（默认拒绝，不是默认允许）。

---

## 10. 错误语义与防用户枚举

| 场景 | HTTP | `code` | 响应体是否区分原因 |
|---|---|---|---|
| 未登录访问受保护接口 | 401 | `authentication_required` | 不区分（沿用现有） |
| 登录：邮箱不存在 | 401 | `invalid_credentials` | **与密码错完全一致**（状态码、code、message、响应耗时都一致） |
| 登录：密码错 | 401 | `invalid_credentials` | 同上 |
| 登录：账号被禁用（将来） | 401 | `invalid_credentials` | 同上（对外不暴露"你被禁用"） |
| 会话过期/已撤销 | 401 | `authentication_required` | 一致 |
| 缺 CSRF 头 / `Origin` 不符 | 403 | `csrf_validation_failed` | 可区分（这不是账号信息） |
| 登录限流 | 429 | `too_many_attempts` | 可区分，且带 `Retry-After` |
| 注册：邮箱已存在 | **见 §18 第 4 项**（取舍待定） | `email_taken` 或统一 202 | — |
| 密码不合规 | 422 | `validation_error` | 可区分（属表单校验，不泄漏账号信息） |

**实现要点**：现有 `AppError` → `{code, message, details}` 的结构已经统一（`app/core/errors.py`），新增错误类直接继承即可，不需要改异常处理器。**新增的 `invalid_credentials` 必须写成与 `authentication_required` 结构完全同形**，避免"响应形状不同"成为侧信道。

---

## 11. 限流与暴力破解

| 维度 | 策略 | 说明 |
|---|---|---|
| 登录：按账号 | 连续失败 5 次 → 指数退避（1s, 2s, 4s… 上限 5 分钟），15 分钟无失败则清零 | 计数放数据库或进程内？**单实例 MVP 用进程内**足够；多实例时换 Redis（届时再引入，不提前） |
| 登录：按 IP | 10 次/分钟 | 防"同一 IP 撞很多账号" |
| 注册 | 5 次/小时/IP | 防批量抢注 |
| 全局 | 每 IP 300 请求/分钟 | 基础保护，挡住明显的脚本 |
| 响应 | 429 + `Retry-After` | 明确告知何时可重试，避免客户端疯狂重试 |
| 副作用 | 失败也在**同一时间预算**内返回 | 不退避反而更快响应会变成"账号存在"的信号 |

**明确不做的**：不做"失败 N 次永久锁定账号" —— 那会变成攻击者用来锁死他人账号的武器（DoS 转向用户）。

---

## 12. 审计日志

只记**事件**，不记**凭据**。

| 事件 | 记录字段 | 禁止记录 |
|---|---|---|
| 登录成功 | `event=auth.login.success`, `user.public_id`, `session.id`, `user_agent` | 密码、令牌原文、令牌哈希 |
| 登录失败 | `event=auth.login.failure`, `reason`（`no_identity` / `bad_password` / `rate_limited`）, 邮箱的**哈希前 8 位**（可关联同一账号的尝试，又不落明文邮箱） | 用户输入的密码、完整邮箱 |
| 退出 | `event=auth.logout`, `session.id` | — |
| 会话撤销 | `event=auth.session.revoked`, `session.id`, `reason` | — |
| 改密 | `event=auth.password.changed`, `user.public_id`, 撤销的会话数 | 新旧密码 |
| 开发身份生效 | 沿用现有 `WARNING` 日志 | — |

**中间件要求**：请求日志必须显式排除 `cookie` / `set-cookie` / `authorization` 头。Phase 2.7 已实测应用日志会把 DSN 密码段掩码成 `***`，这条纪律要延续到请求头。

---

## 13. 开发身份的隔离（Phase 3 必须收口）

现状已有一层保护（`Settings` 构造期拒绝 `production + dev_user_enabled`），Phase 3 要再加两道：

| 层 | 措施 |
|---|---|
| 配置层 | **保持现状**：`APP_ENV=production` + `DEV_USER_ENABLED=true` → 启动即失败。补一条回归测试锁死行为 |
| 解析层 | 顺序改为：**先校验会话 Cookie；无有效会话时，才允许回落到开发身份**（且仍需三重环境门禁） |
| 输出层 | `/health` 与启动日志继续暴露 `auth_mode`（`development_identity` / `unauthenticated` / **新增 `session`**），让"当前到底是什么模式"永远可见 |
| 测试层 | 新增用例：`APP_ENV=production` 且存在任何 Cookie → 一律 401，即使 `DEV_USER_ENABLED` 被误开也无法生效（因为构造期就失败） |

> 设计取舍：**保留**开发身份而不是删掉。理由：Phase 4/5 要写上传与前端，每次调试都真登录一遍会显著拖慢；而它的风险已被三重门禁压到"配置写错才可能触发"，且 `production` 下启动即失败，不是静默放行。

---

## 14. 接口清单（设计）

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | 否 | 邮箱 + 密码 → 建 `users` + `auth_identities`。是否自动登录见 §18 第 5 项 |
| `POST` | `/api/v1/auth/login` | 否 | → 设 Cookie；统一 401 |
| `POST` | `/api/v1/auth/logout` | 是 | 撤销当前会话 + 清 Cookie。**幂等**：已失效也返回 204 |
| `GET` | `/api/v1/auth/me` | 是 | 返回 `public_id` / `display_name` / 邮箱（脱敏显示可选） |
| `GET` | `/api/v1/auth/sessions` | 是 | 列出本人活跃会话（`id` / `issued_at` / `last_seen_at` / `user_agent`），供"设备管理" |
| `DELETE` | `/api/v1/auth/sessions/{id}` | 是 | 撤销指定会话（只能撤自己的，别人的 → 404） |
| `POST` | `/api/v1/auth/password` | 是 | 改密（需当前密码）→ 撤销其他会话 |

**不新增的**：`/auth/forgot-password`、`/auth/reset-password`、`/auth/verify-email` —— 都需要邮件通道，当前没有。

**现有接口的变化**：`/api/v1/items/*` **零改动**。它们已通过 `UserContextDep` 取身份，认证接入后自动受保护。

---

## 15. 实施任务拆分（审核通过后才动手）

| 编号 | 任务 | 主要产出 | 依赖 |
|---|---|---|---|
| T1 | 依赖与密码哈希工具 | 引入 `argon2-cffi`；`app/core/security.py`：`hash_password` / `verify_password` / `needs_rehash` / `dummy_verify`；实测单次耗时并定参 | — |
| T2 | 数据模型 | `AuthIdentity` / `Session` 模型 + Alembic 迁移（含 `upgrade`/`downgrade`） | T1 |
| T3 | 会话服务 | `app/services/session_service.py`：`issue` / `resolve` / `revoke` / `revoke_others` / `purge_expired`；令牌生成与哈希 | T2 |
| T4 | 认证路由 | `app/api/v1/routes/auth.py` + schemas（`extra="forbid"`） | T3 |
| T5 | 统一错误与防枚举 | `InvalidCredentials` / `CsrfValidationFailed` / `TooManyAttempts` | T4 |
| T6 | 限流 | 进程内滑动窗口 + 失败退避（接口留出多实例替换点） | T4 |
| T7 | 身份接入 | 改 `resolve_user_context`：先会话、后开发身份；`UserContext` 增加可选 `session_id`；每条查询仍走仓储 | T3, T4 |
| T8 | CSRF 与 CORS | `Origin` 校验依赖 + double-submit 校验；CORS 显式配置 | T4 |
| T9 | 审计与日志脱敏 | 结构化事件 + 请求头过滤 | T7 |
| T10 | 测试 | 见 §16 | 全部 |

**顺序理由**：T1 先做是因为要先量出哈希耗时在目标机器上的实际值（机器的 CPU 决定参数），否则参数是拍脑袋的。T7 放后面是为了让认证逻辑先独立可测，再接进现有依赖链 —— 避免一上来就改动 104 项测试都依赖的入口。

---

## 16. 测试矩阵（对应路线图验收项）

| 路线图验收项 | 测试用例 |
|---|---|
| 未登录不能访问受保护接口 | 无 Cookie 调 `GET/POST/PATCH/DELETE /items` → 全部 401；`/health` 仍 200 |
| 篡改 user_id / public_id 不能跨用户 | 请求体塞 `user_id`/`public_id` → 422（`extra="forbid"`）；A 的会话拿 B 的 `item_id` → 404；A 的会话 `PATCH`/`DELETE` B 的 item → 404 |
| 篡改 Cookie 不能越权 | 随机令牌 / 改一个字符 / 空值 → 401 |
| 篡改 Token（本方案无 JWT） | 不适用；改为：过期会话 → 401；已撤销会话 → 401；绝对过期 → 401；空闲过期 → 401 |
| 登录有测试 | 正确凭据 → 200 + 两个 Cookie（`HttpOnly` 只在服务端可见）；错误密码 → 401 `invalid_credentials`；不存在邮箱 → **响应与错误密码逐字节相同** |
| 退出有测试 | 退出后同一 Cookie 再请求 → 401；重复退出仍返回 204（幂等） |
| 过期/撤销有测试 | 改密后其他会话失效、当前会话保留；`DELETE /auth/sessions/{id}` 只能撤自己的 |
| 错误凭据有测试 | 缺 CSRF 头 → 403；`Origin` 不在白名单 → 403；限流触发 → 429 + `Retry-After` |
| CORS/CSRF/Cookie 有文档 | 本文档 §9 + 单独的 `docs/runbooks/auth-cookie-policy.md` |
| 开发快捷方式不在生产生效 | `Settings(app_env=production, dev_user_enabled=True)` → `ValidationError`；生产环境带开发身份配置启动 → 失败 |
| 会话固定 | 登录前后 Cookie 值不同；预先手工设置 Cookie 后登录 → 拿到全新令牌 |
| 密码不落日志 | 捕获日志，断言不含明文密码、不含令牌原文 |

**测试隔离**：沿用 Phase 2 的外层事务 + `Session(bind=connection)` 方案（`join_transaction_mode=conditional_savepoint`），保证测试零残留。新增的表要同步加入清理与 `TRUNCATE` 顺序。

---

## 17. 兼容性 / 明确不改动的部分

| 对象 | 是否改动 | 说明 |
|---|---|---|
| `UserContext` | **仅加一个可选字段** `session_id: int \| None = None` | 现有构造调用（含测试）不受影响 |
| `ItemRepository` | ❌ 不改 | 隔离逻辑已正确，认证只是让 `UserContext` 来源变了 |
| `items` 路由与 schemas | ❌ 不改 | 自动受保护 |
| `errors.py` 异常处理器 | ❌ 不改 | 新增错误类继承 `AppError` 即可 |
| `config.py` 开发身份门禁 | ❌ 不改 | 保留，补测试 |
| `sessions` / `auth_identities` | ✅ 新增 | 一次迁移 |
| 迁移 | ✅ 新增 1 个 revision | 需验证 `upgrade` → `downgrade` → `upgrade` 往返 |

---

## 18. 未决问题（**阻塞实现，需你确认**）

| # | 问题 | 选项 | 我的建议 |
|---|---|---|---|
| 1 | **单用户还是多用户注册？** | a) 只有你一个账号，注册接口一次即锁 / b) 开放注册 / c) 邀请码 | **b**：结构上按多用户设计，但开放注册风险低（无敏感资源），将来收紧只需加开关 |
| 2 | **密码策略强度** | a) ≥12 字符（NIST 基线）/ b) ≥8 + 复杂度规则 | **a**：更长比更复杂更有效，且不逼用户写 `P@ssw0rd!` |
| 3 | **会话时长** | a) 空闲 7 天 / 绝对 30 天 / b) 空闲 30 分钟 / 绝对 7 天 | **a**（个人应用，频繁重登只会让人关掉 2FA 心思）；如你更看重安全选 b |
| 4 | **注册时邮箱已存在怎么回？** | a) 409 `email_taken`（好用，但泄漏"该邮箱已注册"）/ b) 统一 202 "已发送邮件"（不泄漏，但需要邮件通道，当前没有） | **a + 限流**。在没有邮件通道的前提下，b 无法真正实现（会变成"假装发信"），说谎比承认更糟 |
| 5 | **注册后是否自动登录？** | a) 自动登录 / b) 要求再登录一次 | **a**：少一步无意义操作；风险由限流覆盖 |
| 6 | **是否现在就做"设备管理"页面？** | a) 只做后端接口 / b) 前后端都做 | **a**：Phase 3 定位是后端认证，前端在 Phase 5 |
| 7 | **生产域名与 HTTPS** | 需要你给出（或确认暂不部署） | 决定 `Secure` 与 `__Host-` 前缀是否启用 |

---

## 19. 本轮明确不做

- 找回密码 / 重置密码 / 邮箱验证（缺邮件通道）
- OAuth / OIDC / Passkey（已在 §4 说明为后续增强）
- 双因素认证（TOTP / WebAuthn）
- 多实例共享限流（换 Redis）
- 用户资料（身高、体型、风格偏好）
- 任何前端登录页 —— 本阶段只做后端，Phase 5 接 UI
- 图片上传与隐私外发策略（Phase 4）
- 审计日志的持久化与查询界面（先写结构化日志）

---

## 20. 审核检查点

请重点确认三件事，其余可按我的建议走：

1. **方案 A（服务端会话 + `HttpOnly` Cookie）是否认可**，尤其是"不用 JWT"这个决定。
2. **§18 第 1、3、4 项**（单/多用户、会话时长、注册冲突语义）—— 这三项直接决定表结构与接口形状，改起来成本最高。
3. **生产部署形态**：是否 `www` + `api` 同站双域名、是否已有 HTTPS 计划。这决定 Cookie 属性能否一次配到位。

确认后我按 §15 的 T1→T10 顺序实施，每个任务完成后跑全量测试并单独提交。
