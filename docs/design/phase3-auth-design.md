# Phase 3：正式身份认证与授权 —— 方案比较与威胁模型

- 日期：2026-10-25
- 版本：**v2（安全复审修订）**。v1 → v2 的主要变化：CSRF 令牌从「跨源 double-submit Cookie」改为「初始化接口下发 + 会话绑定 HMAC 令牌」；会话滑动续期补齐并发与 Cookie 同步规则；开发身份与认证测试矩阵分环境明确；限流补齐部署假设；新增接口级来源校验矩阵。完整差异见 `docs/planning/phase3-auth-design-review.md`。
- 状态：**设计稿，等待审核。尚未编写任何认证代码，未新增依赖，未建表，未改接口，未改配置。**
- 依据：`docs/planning/WearMind-Project-Roadmap.md` §Phase 3、`docs/planning/00-architecture-plan.md` B.7 Q1 与 G.1 第 5 项
- 前置阶段：Phase 2（`UserContext` / `ItemRepository` / 开发身份注入 / 衣物 CRUD，104 项测试）

---

## 0. 一句话结论

> **推荐：服务端有状态会话（不可伪造的随机令牌，放 `HttpOnly` Cookie）+ 邮箱密码（Argon2id）+ 数据库会话表 + 服务端可验证的 CSRF 令牌（`Origin` 校验 + 会话绑定 HMAC 令牌两层）。**
>
> 不使用 JWT 作为浏览器侧会话载体。理由是：本项目的第一个硬需求是**撤销**（退出登录、改密后踢掉旧会话、账号删除），而 JWT 的自包含特性让撤销必须借助额外的黑名单表 —— 那就等于既写了一张会话表、又保留了令牌泄漏无法撤回的风险，复杂度换不到收益。
>
> CSRF 令牌**不再放在可被前端 JavaScript 读取的 Cookie 里**（跨源时前端根本读不到 API 子域的 Cookie，见 §1.1），改为由初始化接口在响应体中下发、前端存内存、请求时回填 `X-CSRF-Token`；令牌用**会话令牌的哈希作为 HMAC 密钥**生成，因此天然绑定会话、无需新增数据库列、也无需新增配置密钥。
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

**这条部署形态直接否决了 v1 的 CSRF 方案（复审问题 1）**：

| 事实 | 后果 |
|---|---|
| `document.cookie` 只能读到**当前源**可见的 Cookie | `www.example.com` 的 JS 读不到 `api.example.com` 设置的 Cookie，**无论是否 `HttpOnly`** |
| v1 的 `wm_csrf` 是 `api` 域下的 host-only Cookie，且要求前端读取 | 在生产形态下**根本读不到** → double-submit 无法成立 |
| 唯一能让前端读到的方式：把 `Domain` 设为父域 `.example.com` | 这会让该 Cookie 对**所有子域**可写可读，等于把 CSRF 令牌暴露给同站任意子域（正是 §3.2 T3 假设的失陷面），并让"子域种 Cookie 覆盖"成为现实攻击 |

> 结论：**不采用父域 Cookie。** CSRF 令牌改走响应体下发（§9.3）。本地开发（同站不同端口）下 v1 能跑通，这正是"本地测试通过、上线即失效"的典型陷阱 —— 复审要求以生产形态为准设计，本地只作为验证环境。

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

| 类别 | 本项目的具体形态 | 对策（编号对应 §15 任务） |
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
| U5 | 恶意站点诱导用户点击，发起 `POST /items` | 以用户身份建数据 | `SameSite=Lax`（跨站 POST 不带 Cookie）+ `Origin` 精确白名单 + 会话绑定的 `X-CSRF-Token` + 写接口强制 `Content-Type: application/json`（触发预检） | 老浏览器忽略 `SameSite` → 靠 `Origin` 兜住；因此 `Origin` 是**必需**而非可选 |
| U6 | 同站子域（`blog.example.com`）发起 CSRF | `SameSite` 不管用（同站） | `Origin` 必须精确匹配白名单；不带 `Origin` 的写请求直接拒绝。该子域也无法**读取** `api.example.com` 的 `/auth/csrf` 响应（CORS 白名单不含它），因此拿不到有效令牌 | 若攻击者能控制 `Origin`（浏览器强制，不能） |
| U6b | **Login CSRF**：诱导受害者用攻击者的凭据登录 | 受害者后续上传的私密照片进了攻击者的账号；或诱导注册 | 登录/注册同样强制 `Origin` 校验 + 强制 `Content-Type: application/json`；注册不返回受害者账号信息 | 无（见 §9.6 为何此处不要求 CSRF 令牌） |
| U7 | XSS 读走令牌 | 长期冒充 | `HttpOnly` 让 JS 读不到会话 Cookie；`HttpOnly` 是**本方案的核心收益** | XSS 仍可"代用户发请求"，且**能读到内存中的 CSRF 令牌**（它本来就在 JS 侧）—— 但拿到 CSRF 令牌并不比"直接发请求"更强，故不构成额外损失。防线是 CSP 与不引入不可信脚本，属 Phase 6 硬化 |
| U8 | 撞库：拿别的站泄露的邮箱密码来试 | 账号被接管 | Argon2id 慢哈希 + 登录限流 + 统一错误（不告诉攻击者"这个邮箱存在"） | 无法根除，只能降速 |
| U9 | 攻击者遍历邮箱判断谁注册过 | 拿到用户名单 | 登录失败统一 `401`；注册冲突返回 `409 email_taken`（**已知并接受**，见 §10 末尾） | 注册接口天然会泄漏存在性，用 5 次/小时/IP 限流压制，不做假的 202 |
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

技术上更"现代"，但本项目当前是**小规模多用户应用**（开放注册，但用户量预期在几十人以内）：引入 GitHub/Google 登录意味着要注册 OAuth App、处理回调域名、做账号绑定与解绑、处理 IdP 不可用时的降级 —— 全是当前不需要的复杂度，且**没有解决授权问题**（OAuth 只回答"你是谁"，不回答"这件衣服是不是你的"，后者仍靠仓储隔离）。

保留扩展位：数据模型上用 `auth_identities(provider, subject)` 多行设计，将来加 `github` / `google` 只是插入新行，不动 `users` 与 `items`。

**为什么不用 Passkey（E）**

体验最好、抗钓鱼最强，但要求 HTTPS（本地开发要绕）、要求设备支持、且丢失设备后的恢复流程复杂。适合作为**后续增强**，不适合作为第一个认证实现。

---

## 5. 推荐方案（方案 A 的具体形态）

```
登录 POST /auth/login          （无 Cookie 可用，见 §9.6 预认证规则）
  ├─ 校验 Origin 在白名单；要求 Content-Type: application/json
  ├─ 限流（IP + 账号）+ 并发哈希上限（§8.1）
  ├─ 查 auth_identities(provider='password', subject=normalize_email(email))
  ├─ 不存在 → 仍执行一次等参数的假哈希校验（§10.3），返回统一 401
  ├─ Argon2id 校验失败 → 统一 401（不区分"无此账号"与"密码错"）
  ├─ 成功 → 新建 session（32B 随机令牌），存 SHA-256 哈希
  └─ 200 { user, csrf_token }            ← CSRF 令牌随响应体下发，前端存内存
       + Set-Cookie: wm_session=<raw>; HttpOnly; Path=/; SameSite=Lax; Max-Age=604800; [Secure]

首次进入 / 刷新页面 / 令牌过期后重新取
GET /auth/csrf                  （需有效会话）
  └─ 200 { csrf_token, expires_in }     Cache-Control: no-store

写请求 POST/PATCH/DELETE /items
  ├─ 1. Origin 校验（缺失即拒绝）
  ├─ 2. 解析会话：Cookie → SHA-256 → 查 sessions.token_hash
  │     └─ 无此哈希 / 已撤销 / 过绝对期 / 过空闲期 → 401 + Set-Cookie 清除
  ├─ 3. 校验 X-CSRF-Token：HMAC 以 session_token_hash 为密钥，覆盖 nonce+ts
  │     └─ 缺失 / 不匹配 / 过 TTL → 403 csrf_validation_failed
  ├─ 4. 节流滑动续期：条件 UPDATE 命中时，同一响应里重发 Set-Cookie（§7.2）
  └─ 5. 构造 UserContext(origin=authenticated, session_id=...) → 仓储
```

**选它的三条决定性理由**

1. **撤销是一行 `UPDATE ... SET revoked_at = now()`**，没有"令牌还在有效期内但我已踢人"的窗口。
2. **没有签名密钥**，少一个必须轮换、必须保密的配置项。
3. **改动面最小**：`UserContext` / `ItemRepository` / `items` 路由全部不动，只替换 `get_user_context` 的实现。

> 第 2 条的连带好处：会话一被撤销，CSRF 令牌的 HMAC 密钥（= 会话令牌哈希）就随会话失效，**不需要单独维护 CSRF 撤销列表** —— 见 §9.3。

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
| `email_verified` | `BOOLEAN` | `NOT NULL DEFAULT false` | 预留。当前无邮件通道，注册后直接为 `false` 但**不阻塞登录**（决策 D3） |
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
| `revoked_reason` | `VARCHAR(32)` | `NULL`，`CHECK IN ('logout','password_change','admin','superseded','idle_expired','absolute_expired')` | 区分"用户主动退出"与"被踢/自然过期"，排障必需（v2 补两个过期值，见 §7.1） |
| `user_agent` | `VARCHAR(255)` | `NULL` | 截断存储，供"我的登录设备"列表。**不存 IP**（隐私：IP 属个人数据，且 IPv6 前缀即可定位到户） |

索引：

| 名称 | 列 | 用途 |
|---|---|---|
| `uq_sessions_token_hash` | `token_hash` UNIQUE | 每次请求的校验路径 |
| `ix_sessions_user_id_revoked_at` | `(user_id, revoked_at)` | "列出我的活跃会话" / "踢掉该用户所有会话" |

**为什么 `token_hash` 用 `BYTEA` 而非 `VARCHAR`**：`SHA-256` 天然是 32 字节二进制，`BYTEA` 定长、比较更快、也不会出现大小写/编码不一致。用 `hex` 字符串存也可行，但等于把体积翻倍且引入编码歧义。

> **v2 说明：CSRF 令牌不建列。** 令牌由 `HMAC-SHA256(key = token_hash, msg = "wm-csrf-v1" || nonce || ts)` 现场生成与校验（§9.3），因此不需要存储、不需要轮换表，会话一撤销令牌自动失效。这是把"CSRF 状态"折叠进"会话状态"的直接收益。

### 6.4 邮箱：规范化、格式校验与并发唯一性

这三件事必须当成**一条链**来设计，否则会出现"校验过了但库里两条"的经典事故。

| 环节 | 规则 | 归属 | 为什么不能放到别处 |
|---|---|---|---|
| 1. 传入 | 请求体 `email` 为 `str`，`extra="forbid"`；长度先做粗筛（≤254） | Pydantic schema | 防止超长输入进入 SQL 参数与日志 |
| 2. 规范化 | `normalize_email(raw) = raw.strip().lower()` —— **唯一入口**，注册 / 登录 / 改密 / 将来找回密码全部调用 | `app/core/security.py` 或 `app/services/email.py` | 分散实现必然出现 `A@x.com` 与 `a@x.com` 两个账号 |
| 3. 格式校验 | 单个 `@`；本地部分 1–64 字符且**不以点开头/结尾**、无连续点；域名含 `.`、仅 `[a-z0-9.-]`、无前后点；总长 ≤254。**不追求 RFC 5322 全集** | 同上，纯函数 | 用"严格 RFC 正则"既不可读也仍然会拒绝合法地址，收益为负 |
| 4. 唯一性 | **只由数据库约束 `uq_auth_identities_provider_subject` 裁决** | 数据库 | 应用层 `SELECT ... WHERE subject=?` 再 `INSERT` 在并发下是 TOCTOU 漏洞 |
| 5. 冲突处理 | 捕获该唯一约束的 `IntegrityError` → `409 email_taken`；**同一个事务内整体回滚**，不留孤儿 `users` 行 | 服务层 | 先建 `users` 再建身份若失败不回滚，会留下"没有登录方式的空账号" |

**并发注册的具体时序**（必须写进测试）：

```
请求 A ──┐
         ├─ 同时 normalize → 同为 "a@x.com" → 同时 INSERT auth_identities
请求 B ──┘
         ├─ 数据库唯一索引串行化：一个成功，另一个抛 IntegrityError(23505)
         └─ 失败方：ROLLBACK → 409 email_taken（不是 500，也不是 201）
```

**不做的**：不做"邮箱变更"功能（Phase 3 范围外）；不做大小写敏感登录（现实中只会造成"我明明注册过"的困惑）；不引入 `citext` 扩展（多一个部署依赖，换不到任何安全性）。

> 明确承认：`lower()` 只处理 ASCII 大小写，对含非 ASCII 的国际化邮箱可能产生歧义。Phase 3 的格式校验只接受 ASCII 域名与常规字符集，国际邮箱暂不支持 —— 这比"看起来支持但唯一性不可靠"要好。

### 6.5 `email_verified=false` 且允许登录：这不是"小瑕疵"，是三条硬限制

| 风险 | 具体后果 | 为什么本轮接受 | 缓解 |
|---|---|---|---|
| **邮箱可能不属于注册者** | 任何人可以用 `someone@example.com` 注册。真正的邮箱主人永远无法用该地址注册（`409 email_taken`），也**无法找回** | 修它需要邮件通道（发验证信），本轮明确没有 | 文档与 UI 文案措辞为"登录邮箱"而非"已验证邮箱"；不做任何"邮箱可信"的推断 |
| **打错一个字即永久失联** | `a@gmial.com` 注册成功且能登录（自己记得住），但一旦忘记密码就再无救 | 同上（无找回密码） | **必须在界面上明说**："忘记密码将无法找回，请自行妥善保管"；注册页不做"记住我"以外的邮箱用途承诺 |
| **邮箱不能作为身份凭证扩展** | 将来的"邀请""通知""跨设备找回"都不能基于它 | 功能未做 | `email_verified` 列先留着，**将来只在验证通过后才置 true**；任何依赖"邮箱可信"的功能必须先做验证 |

**由此得出的最硬的一条限制**（必须让用户知道，而不是藏在设计文档里）：

> **本阶段没有自助找回密码，也没有邮箱验证。账号一旦忘记密码，即等于永久丢失；注册时填错邮箱也无法更正。**

这不是"以后补"就能抹平的 —— 它决定了 Phase 3 的产品定位是"可用但有明确失联风险"。路线图里的"找回密码"应视为**与认证同等优先**的后续项，而不是可选增强。

---

## 7. 令牌与会话生命周期

### 7.1 令牌形态与解码规则（精确到字节）

| 项 | 取值 | 理由 |
|---|---|---|
| 令牌熵 | **256 bit**（`secrets.token_bytes(32)`） | 远超暴力破解可行范围 |
| 传输形态 | `base64url` **无填充**（43 字符，字符集 `A-Za-z0-9-_`） | URL/Cookie 安全、无歧义字符 |
| 是否加值前缀 | **否**。`wm_` 之类前缀**不放进 Cookie 值** | 前缀一旦进入值域，就必须在哈希前后严格区分"剥不剥"，是极易出错的地方；且自定义前缀对 GitHub secret scanning 无效（它只认已登记的合作方格式）。识别与脱敏靠 **Cookie 名**（`wm_session` / `__Host-wm_session`）与日志正则，不靠值前缀 |
| 解码步骤（服务端，严格顺序） | ① 取 Cookie `wm_session` 原值 → ② 若长度 ≠ 43 或含非 base64url 字符 → 直接视为无效（**不做 trim、不做大小写纠正**）→ ③ 按 ASCII 字节计算 `SHA-256` → ④ 用 32 字节结果查 `sessions.token_hash` 唯一索引 | 任何"宽容处理"（trim、补 padding、忽略大小写）都会扩大等价令牌集合，等于降低有效熵 |
| 哈希输入的精确定义 | `SHA-256( 43 个 base64url 字符的 ASCII 字节 )`。**不含** Cookie 名、**不含** `wm_session=`、**不含**引号、**不含** base64 解码后的 32 字节原始随机数 | 这是最容易在实现与测试之间产生分歧的一处，必须钉死：**哈希的是"传输形态的字符串"，不是"随机源字节"** |
| 服务端存储 | `SHA-256(raw)` | 令牌本身是高熵随机数，**不需要** Argon2（那是给低熵密码用的；对 256-bit 随机值用慢哈希只会让每次请求多花几十毫秒，纯浪费） |
| 校验方式 | 唯一索引命中即通过；**不做字符串比较**，也无需常量时间比较（比较的是索引键，不是秘密） | — |
| 空闲超时 | **7 天**（`last_seen_at` 起算） | 一周不用才要求重新登录，符合预期 |
| 绝对超时 | **30 天**（`absolute_expires_at`，签发时写死） | 硬上限，防止"一直用就一直有效"的无限会话 |
| 登录时 | **必定新建会话**，绝不复用客户端送来的任何值 | 防会话固定（U10） |
| 令牌轮换 | **不做**每请求轮换 | 会引入并发请求互相踢掉的经典 bug（同一页面的并行请求拿着新旧两个令牌，谁先到谁后到不确定），收益不抵成本 |
| 退出 | `revoked_at = now()`, `revoked_reason='logout'` + 清 Cookie | 立即失效 |
| 改密 | 撤销该用户**其他**所有会话（`revoked_reason='password_change'`），当前会话保留 | 被盗后用户能自行收回（U11） |

**有效性的四个判据（任一命中即无效）**：

```
revoked_at IS NOT NULL                       → 无效（退出 / 改密被踢 / 管理员）
now() >= absolute_expires_at                 → 无效（绝对过期）
now() - last_seen_at >= interval '7 days'    → 无效（空闲过期）
token_hash 查不到                             → 无效（伪造 / 已被清理）
```

前三条是**查询条件**，不是应用层 `if`。也就是校验 SQL 长这样（`token_hash` 唯一索引命中后立刻判四件事）：

```sql
SELECT id, user_id, issued_at, last_seen_at, absolute_expires_at
  FROM sessions
 WHERE token_hash = :hash
   AND revoked_at IS NULL
   AND absolute_expires_at > now()
   AND last_seen_at > now() - interval '7 days';
```

> 为什么把时间条件放进 SQL 而不是取出来再判断：避免"查到了但判断写漏一个分支"这类错误；也让并发撤销（另一事务刚 `UPDATE revoked_at`）在 READ COMMITTED 下被正确排除 —— 校验发生在同一条语句的快照里。

### 7.2 滑动续期：数据库时间与浏览器 Cookie 必须同步演进

这是复审问题 2 的核心。**最容易出的错是：以为更新了 `last_seen_at` 就等于浏览器 Cookie 也续上了。**

**两条独立的时钟**

| 时钟 | 由谁维护 | 判据 | 如何前进 |
|---|---|---|---|
| 服务端空闲窗口 | `sessions.last_seen_at` | `now() - last_seen_at < 7d` | 节流写库 |
| 浏览器 Cookie 寿命 | 浏览器 | `Set-Cookie` 里的 `Max-Age` | **只在该响应携带 `Set-Cookie` 时才前进** |

如果只写库不发 `Set-Cookie`：浏览器在最初 7 天后就丢弃 Cookie → 用户在"服务端认为还活着"的状态下被踢出（体验 bug，但方向安全）。
如果只发 `Set-Cookie` 不写库：浏览器比服务端活得久 → **真空洞**（服务端已判定空闲过期，浏览器却继续送 Cookie，用户看到"随机掉线"）。

因此定一条不可拆分的规则：

> **续期是"一个动作、两个效果"：`last_seen_at` 的条件 UPDATE 与 `Set-Cookie` 的发出，由同一个布尔量控制。`rowcount == 1` 才发 `Set-Cookie`；`rowcount == 0` 一定不发。**

**具体规则**

| 项 | 规则 |
|---|---|
| 何时尝试写 `last_seen_at` | 每个**通过身份解析**的请求都尝试（含 GET；读也算活跃）。**排除**：`/health`、身份解析失败的请求（401）、CSRF 校验失败的请求（403）—— 攻击流量不应该延长受害者会话 |
| 节流阈值 | `5 分钟`。即「距上次记录 ≥5 分钟」才真正写库 |
| 写入语句（条件更新，无读-改-写） | `UPDATE sessions SET last_seen_at = now() WHERE id = :sid AND revoked_at IS NULL AND absolute_expires_at > now() AND last_seen_at < now() - interval '5 minutes'` |
| 为何不先 SELECT 再 UPDATE | 读-改-写在并发下会丢失更新，且要额外锁；条件更新是幂等的，多个并发请求只有一个 `rowcount=1`，其余为 0，天然正确 |
| 何时重发 `Set-Cookie` | **仅当** ① 登录/注册签发新会话；② 上述条件更新 `rowcount=1`；③ 401 清除路径；④ 退出清除路径。其余情况一律不发 |
| `Max-Age` 取值 | `Max-Age = min(7 天, absolute_expires_at - now)`（秒）。正常情况恒为 `604800`；当会话接近 30 天绝对上限时自动缩短，保证 Cookie 不会比会话活得久 |
| 绝对过期如何检查 | 每次校验都在 SQL 里比 `absolute_expires_at > now()`（§7.1），**与 `Max-Age` 无关**。不依赖浏览器"记得"过期时间 —— 客户端时钟、休眠唤醒、手动改系统时间都会让本地过期不可信 |
| 过期后的收尾 | 读到"存在但已过期"的行时，best-effort 写 `revoked_at` + `revoked_reason`（`idle_expired` / `absolute_expired`），并返回 401 + 清 Cookie。**写失败不影响 401**（宁可漏记审计，不可漏放行） |
| 已撤销/已过期时的 Cookie | 401 响应附 `Set-Cookie: wm_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax; [Secure]`，让前端下一次请求就是干净的未登录态 |
| 并发请求 | 见 §7.4 |

**允许的偏差（明确写出来，避免过度设计）**

- 并发请求各自计算出的 `Max-Age` 可能相差几毫秒，浏览器取最后一次到的值。可忽略。
- 若响应在网络上丢失（用户断网），库已续期、Cookie 未续 → 下次请求若 Cookie 还在（未到 7 天）则继续，若已丢则重新登录。方向安全。
- 若反向代理缓存了 `Set-Cookie` 响应 → **必须禁止**：所有认证相关响应统一 `Cache-Control: no-store`（§9.5）。

### 7.3 一个请求内的事件顺序（决定续期与 CSRF 的先后）

```
1. Origin 校验（写请求）
2. 解析会话（SQL 四判据）           ← 失败：401，不续期
3. 校验 CSRF 令牌（写请求）         ← 失败：403，不续期
4. 触发节流续期（条件 UPDATE）      ← 只有到这里才可能续期
5. 构造 UserContext → 路由处理
```

顺序理由：CSRF 失败说明请求可能来自攻击者，**不能让它延长受害者会话**（否则攻击者可以用无效 CSRF 请求把会话"钉"在活跃状态，抵消空闲超时的保护）。GET 无第 3 步，直接到第 4 步。

### 7.4 并发与撤销的边界（说清楚"做不到什么"）

| 情形 | 行为 | 说明 |
|---|---|---|
| 同一页面 6 个并行请求 | 全部读到同一 `last_seen_at`；最多一个 `rowcount=1` | 无锁，无丢失更新，因为写入是"设为 `now()`"而非"加一" |
| 续期与撤销并发 | 撤销先提交则续期 `rowcount=0`（`revoked_at IS NULL` 不满足） | 撤销优先，符合直觉 |
| 已发出、尚未完成的请求 | **可能仍成功** | 撤销不是"秒断连接"，它只保证**后续请求**被拒。残余风险的上界 = 单个请求的处理时长 |
| 多个 worker / 多实例 | 上述规则与实例数无关（状态在库里，不在进程内存） | 这是把会话放数据库的连带收益；**限流**则不是，见 §11 |
| 会话表无限增长 | 过期行不删（保留审计），需 `purge_expired` 定期把超绝对期 N 天后的行物理删除或归档 | Phase 3 先留接口与文档，不建定时任务 |

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
| 时间侧信道 | 账号不存在时也执行一次**参数完全相同**的假哈希校验（对固定的 dummy PHC 串） | 否则"响应快 = 账号不存在"（U9）。**可测试的表述见 §10.3，不承诺"耗时绝对一致"** |

### 8.1 Argon2id 的成本必须按"并发"评估，不能只看单次耗时

`memory_cost=64 MiB` 是**每个正在计算的哈希**占 64 MiB，不是总共 64 MiB。40 个并发登录 = 2.5 GiB 瞬时占用，足以让 4 GiB 的机器 OOM —— 攻击者不需要破解密码，只要并发打登录接口就能把服务打死（§3.3 的 D）。

| 量 | 取值方式 | 验收标准 |
|---|---|---|
| 单次耗时 | T1 在**目标机器**上实测 `verify` 的中位数（不是 `timeit` 的最小值） | 落在 **50–200 ms**；低于 50 调高 `time_cost`，高于 200 调低 `memory_cost` 或换 `parallelism` |
| 单次峰值内存 | 实测进程 RSS 增量 | 与 `memory_cost` 同量级（±20%） |
| 并发上限 | **信号量限流**：同时进行的哈希计算 ≤ `AUTH_HASH_CONCURRENCY`（默认 **4**，即 256 MiB 峰值） | 超出者排队等待；排队时间也计入 §10.3 的等时预算 |
| 机器余量 | 记录目标机器可用内存，确保 `并发上限 × memory_cost` ≤ 可用内存的 25% | 写进 T1 的实测报告 |
| 队列本身的风险 | 排队意味着攻击者可以占满槽位，让**合法登录变慢**（低成本的 DoS） | 靠 §11 的登录限流把"能占到槽位"的请求数量压下去；两者必须同时存在 |

> 这一条是 v2 新增的：v1 只写了"实测单次耗时"，没有写并发内存，等于漏掉了最容易打崩服务的那一面。

---

## 9. Cookie / CORS / CSRF

### 9.1 Cookie（v2：只剩一个 Cookie）

> v1 有两个 Cookie（`wm_session` + `wm_csrf`）。v2 **删掉 `wm_csrf`**，原因见 §1.1：跨源时前端读不到它。CSRF 令牌改走响应体（§9.3）。

| 属性 | 会话 Cookie |
|---|---|
| 名称（开发） | `wm_session` |
| 名称（生产，`COOKIE_SECURE=true`） | `__Host-wm_session` |
| `HttpOnly` | ✅ **是**（核心收益：XSS 读不到，也就无法把令牌外带） |
| `Secure` | 生产 ✅；开发（`http://localhost`）关闭 |
| `SameSite` | `Lax` |
| `Path` | `/` |
| `Domain` | **不设置**（host-only） |
| `Max-Age` | `min(7 天, absolute_expires_at - now)`，正常恒为 `604800` |
| `Expires` | 不设置（只发 `Max-Age`，避免两者冲突） |

> `__Host-` 前缀强制 `Secure` + `Path=/` + 无 `Domain`，浏览器会拒绝不合规的同名 Cookie —— 这是防"子域种 Cookie 覆盖"的低成本加固。开发环境因走 http，使用普通名 `wm_session`。
>
> **为什么不再需要第二个 Cookie**：CSRF 令牌不进 Cookie，就不存在"该不该 `HttpOnly`"的两难，也不存在父域暴露问题。少一个 Cookie 也少一处 `Max-Age` 需要与库同步的地方（§7.2 的两时钟问题只剩一个时钟）。

### 9.2 CORS

| 项 | 取值 | 理由 |
|---|---|---|
| `allow_origins` | **精确白名单**（来自 `CORS_ORIGINS`，已是逗号分隔配置） | 带凭据的请求**禁止** `*`（浏览器也会拒绝） |
| `allow_credentials` | `True` | 否则浏览器不发送/不接收 Cookie |
| `allow_methods` / `allow_headers` | 显式列出（需含 `X-CSRF-Token`） | 不用 `*`，避免放宽过头 |
| `expose_headers` | 不需要（令牌在响应体里，不在自定义响应头里） | 少一项要维护的白名单 |
| `Vary: Origin` | **必须存在**（认证相关响应） | 否则共享缓存可能把带 `Access-Control-Allow-Origin: 合法源` 的响应返回给另一个源 |
| `Cache-Control` | `no-store`（所有认证/会话相关响应） | 令牌与会话态绝不能进任何缓存 |
| 前端 | `fetch(..., { credentials: 'include' })` | 缺失则 Cookie 不会跨源携带 |

> **CORS 配好了只说明"别的源读不到响应"，不说明"别的源发不出请求"** —— 这一点单独在 §9.7 展开，因为它是本项目最容易误判的地方。

### 9.3 CSRF：`Origin` 校验 + 会话绑定令牌（v2 重写）

| 层 | 机制 | 挡住什么 | 挡不住什么 |
|---|---|---|---|
| 1 | `SameSite=Lax` | 跨**站** `POST`/`PUT`/`DELETE` 根本不带 Cookie（连"以谁的身份"都不成立） | 同站子域（U6）；老浏览器；**登录/注册这类本来就没 Cookie 的请求完全不适用** |
| 2 | **`Origin` 精确校验**（所有写请求强制，缺失即拒绝） | 跨站与同站子域的伪造请求；来源不明的请求；Login CSRF（U6b） | 精确白名单内被攻陷的前端（那时攻击者已在源内，属 XSS 而非 CSRF） |
| 3 | **`X-CSRF-Token` 校验**（仅对"带会话 Cookie 的写请求"） | 白名单配错时的兜底（配错的源也读不到本会话的令牌）；代理/中间件改写请求；跨会话重放 | 源内 XSS（它可以直接读令牌） |

> 为什么不只用 `SameSite=Strict`：`Strict` 会让"从外部链接点进来"的首次请求不带 Cookie，用户会看到"已登录却被弹回登录页"，体验明显变差；且它只解决"站"的粒度，对同站子域完全无效。`Lax` + `Origin` + 令牌是更好的组合。

**第 3 层为什么必须"会话绑定"而不是"随机串比对"**

随机串比对（含 double-submit）的本质是"客户端能证明自己拿到过某个串"。若这个串由服务端下发且**不与身份绑定**，那么任何能拿到串的人都能把它用在任何会话上；同时对**匿名接口**更是形同虚设（谁都能取一个）。会话绑定把"拿到串"升级为"必须是这个会话的持有者才推导得出串"。

**令牌构造（无需新密钥、无需新增列）**

```
key      = session_token_hash                       # 32B，服务端由 Cookie 推出，客户端不可知（HttpOnly）
nonce    = secrets.token_bytes(16)
ts       = int(utc_now().timestamp()).to_bytes(4, 'big')
mac      = HMAC-SHA256(key, b"wm-csrf-v1" + nonce + ts)[:16]
token    = b64u(nonce) + "." + b64u(ts) + "." + b64u(mac)      # ≈52 字符
```

校验（服务端）：

```
1. 结构：恰两个 "."，三段都能 base64url 解码，nonce=16B / ts=4B / mac=16B，否则 403
2. 时效：0 <= now - ts <= 12h，否则 403 csrf_token_expired
3. 密钥：key 来自**刚刚校验通过的会话行**的 token_hash（不是客户端传的）
4. 比对：hmac.compare_digest(收到 mac, 重算 mac)，不等则 403 csrf_token_invalid
```

| 为什么这样设计 | 说明 |
|---|---|
| **不新增配置密钥** | 密钥是会话令牌哈希，本来就在库里；§4.3 的"零签名密钥"结论仍然成立 |
| **天然会话绑定** | 不同会话 → 不同 `token_hash` → 同一 `mac` 必然验不过。攻击者拿到 A 的令牌，配 B 的 Cookie 使用 → 403 |
| **天然随撤销失效** | 会话被撤销/过期 → 第 2 步（会话解析）就 401，根本走不到 CSRF 校验。**不需要 CSRF 撤销表** |
| **多标签页友好** | 令牌**无状态、可并存**：任意多个 nonce 同时有效。这正是不采用"每次取令牌就轮换"的原因（轮换会让先开的标签页立刻失效） |
| **泄库影响有限** | 库里有 `token_hash`，能算出 `mac`，但没有原始令牌 → 无法通过会话认证 → 单有 CSRF 令牌毫无用处 |
| **令牌不泄漏会话** | HMAC 输出不可逆推 key，令牌本身不含会话任何片段 |

**关键顺序：先认证，后 CSRF。** CSRF 校验依赖"已解析出的会话"，所以顺序不可颠倒。反过来说，401 的优先级高于 403 —— 未登录时不给"你的 CSRF 令牌错了"这种无意义反馈。

### 9.4 令牌的六个生命周期问题（逐个回答）

| # | 问题 | 结论 |
|---|---|---|
| 1 | **如何生成** | 上节公式。`nonce` 每次新取，**不复用**；同一个会话可以有无限多个有效令牌 |
| 2 | **如何与会话绑定** | 以 `sessions.token_hash` 为 HMAC 密钥。服务端用的 key 来自数据库校验通过的那一行，**绝不取请求里任何自报字段** |
| 3 | **未登录时的登录/注册如何保护** | **不要求 CSRF 令牌**，改由 `Origin` 严格校验 + 强制 `Content-Type: application/json`（触发预检）来保护。理由与反例见 §9.5 —— 给匿名接口发"谁都能领"的令牌是安全表演 |
| 4 | **登录成功后如何建立新状态** | 登录/注册的 200/201 响应体**直接带上新会话的 `csrf_token`**（省一次往返，也避免"前端先写请求后取令牌"的竞态）。前端同时丢弃旧令牌（旧令牌属于旧会话/匿名状态，本来就验不过） |
| 5 | **退出/撤销/过期如何失效** | 令牌无存储，失效靠"会话先失效"：退出 → 会话 `revoked_at` 有值 → 后续请求 401；改密踢其他会话 → 那些会话 401；空闲/绝对过期 → 401。前端在退出成功回调里清空内存中的令牌 |
| 6 | **如何防止跨用户/跨会话复用** | 见下节对照表 |

**跨用户/跨会话复用为什么不可能**

| 攻击尝试 | 结果 | 原因 |
|---|---|---|
| 用 A 的令牌 + B 的 Cookie | 403 | key 是 B 的 `token_hash`，A 的 mac 用 A 的 key 生成 |
| 用自己会话的令牌打别人接口 | 403（先在 CSRF 一步失败）；即便绕过也是 404 | 令牌只证明"同源且同一会话"，**不是身份**；越权仍由仓储 `WHERE user_id=?` 挡 |
| 把令牌当认证凭据（不带 Cookie 只带 `X-CSRF-Token`） | 401 | 身份只来自会话 Cookie；**CSRF 令牌永远不作为身份载体** |
| 复用 12 小时前的旧令牌 | 403 `csrf_token_expired` | 时间窗校验 |
| 复用已退出会话的令牌 | 401（不是 403） | 会话解析先行 |

### 9.5 为什么登录/注册不发 CSRF 令牌（含被否决的备选）

直觉上"所有写接口都要令牌"更整齐，但对**匿名**接口必须算一笔账：令牌由 `GET /auth/csrf` 下发，而该接口在匿名场景下必须对任何人开放（否则没法登录）。攻击者只要能取到令牌，令牌就挡不住他 —— 问题变成"攻击者的浏览器能否读到那个响应体"：

| 攻击位置 | 能否读到 `/auth/csrf` 响应体 | 结论 |
|---|---|---|
| 恶意页面（浏览器内） | ❌ 跨源读取被 CORS 阻断（`allow_origins` 不含它） | 看起来能挡 |
| 攻击者自己的服务器（先取令牌，再把令牌塞进发往受害者的表单） | ✅ 能取到 —— 且因为令牌不绑会话，它**在受害者浏览器里同样有效** | **挡不住** |

第二行是决定性的：匿名令牌无法绑定"是谁的浏览器"，服务端也无从区分"这个令牌是给受害者发的还是攻击者自己领的"。要补上这个洞只能把 `Origin` 编进 MAC，但服务端调用时可以任意伪造 `Origin` 头 —— 又绕回去了。**结论：对匿名接口，`Origin` 是唯一有效的那一层，加令牌只会制造"已防护"的错觉。**

| 备选 | 为什么否决 |
|---|---|
| 匿名 double-submit（服务端种 Cookie，前端读来回填） | 生产中前端读不到 API 子域的 Cookie（§1.1），本问题就是要修掉它 |
| 把 Cookie `Domain` 设为父域让前端可读 | 令牌对所有子域可读可写，等于把 CSRF 防护交给"所有子域都不失陷"这个假设（§3.2 T3 明确假设它会失陷） |
| 匿名令牌绑 `Origin` 进 MAC | 服务端到服务端调用可伪造 `Origin`，绑定失效 |
| 要求登录请求带一次性 nonce（服务端缓存） | 需要跨请求状态（Redis 或表），与"不提前引入外部存储"冲突，收益仍被第二行抵消 |

**因此登录/注册的防护是**：`Origin` 严格校验（缺失即拒绝）+ `Content-Type: application/json` 强制（非简单请求 → 预检 → 恶意源拿不到 `Access-Control-Allow-Origin`）+ `SameSite=Lax`。三条都是浏览器强制的，攻击者无法伪造。

> 顺带说明：登录接口即便被 CSRF 成功（Login CSRF），攻击者得到的也只是"受害者以攻击者身份操作"，**不能**读取受害者已有数据（那些数据属于另一个 `user_id`，仓储隔离仍生效）。真正的危害是"受害者新上传的内容进了攻击者账号"（U6b）—— 已由 `Origin` 校验阻断。

### 9.6 接口级：`Origin` 与 CSRF 规则矩阵（复审问题 5）

| 接口 | 方法 | 需要 `Origin` | 需要 `X-CSRF-Token` | 需要会期 | 依据 |
|---|---|---|---|---|---|
| `/auth/register` | POST | ✅ 强制 | ❌ 否 | ❌ | 匿名接口，§9.5 |
| `/auth/login` | POST | ✅ 强制 | ❌ 否 | ❌ | 同上；Login CSRF 由 `Origin` 挡 |
| `/auth/logout` | POST | ✅ 强制 | **仅当携带有效会话时** | 可选 | 无有效会话 → 204（无可撤销之物，也无状态变更）；有会话 → 令牌必需 |
| `/auth/password`（改密） | POST | ✅ 强制 | ✅ 必需 | ✅ | 高危操作：改密 + 踢其他会话 |
| `/auth/sessions/{id}` | DELETE | ✅ 强制 | ✅ 必需 | ✅ | 撤销他人设备 = 账号接管后的常见动作，必须防护 |
| `/auth/csrf` | GET | ❌ 不要求 | ❌ | ✅ | 无状态变更；响应受 CORS 保护，跨源读不到；`no-store` |
| `/auth/me`、`/auth/sessions` | GET | ❌ 不要求 | ❌ | ✅ | 安全方法，无副作用（读取仍受 CORS 限制） |
| `/items` 系列写操作 | POST/PATCH/DELETE | ✅ 强制 | ✅ 必需 | ✅ | 用户数据的实际写入点 |
| `/items` 系列读操作 | GET | ❌ 不要求 | ❌ | ✅ | 同上 |
| `/health` | GET | ❌ | ❌ | ❌ | 运维探针，不含用户数据 |

**三条通用规则（写在依赖里，不在每个路由里重复判断）**

1. **写方法（除 `GET`/`HEAD`/`OPTIONS`）一律要求 `Origin`，缺失即 403。** 不存在"没有 `Origin` 就放行"的分支。
2. **只要请求携带了会话 Cookie 且写方法 → 必须带 `X-CSRF-Token`。** 无例外、无"内部调用"豁免。
3. **`X-Requested-With`、`Referer`、自定义 `X-Client-*` 头都不作为防护依据** —— 都能被非浏览器客户端自由设置，把它们当防护等于没有防护。

**非浏览器客户端（`curl` / 脚本 / 未来的 CLI）的安全边界**

| 问题 | 结论 |
|---|---|
| 能否靠"缺 `Origin` + 带某个特殊头"放行 | **不能**。这会把"可伪造的请求头"变成身份凭证，是复审明确禁止的 |
| 那这些客户端怎么调试 | 用**开发身份**（`APP_ENV=development` + 三重门禁），或写测试时直接注入会话记录；生产环境不接受无 `Origin` 的写请求 |
| 将来真需要 API 客户端 | 另起一条**独立认证面**（`Authorization: Bearer <API token>`，令牌单独签发、单独撤销、不与 Cookie 混用），届时 Cookie 路径的 CSRF 规则完全不变。本轮不做 |

### 9.7 CORS 不是 CSRF 防护（必须写在文档里，防止误判）

| 概念 | 管什么 | 不管什么 |
|---|---|---|
| CORS | 控制**跨源读取响应**（浏览器是否把响应体交给 JS） | **不管请求是否发出、是否被执行** |
| CSRF | 防止**跨站伪造请求被执行** | 不控制响应可读性 |

攻击者可以构造**简单请求**（`Content-Type: text/plain` / `application/x-www-form-urlencoded` / `multipart/form-data`）绕过预检，请求照常到达服务端并被执行，只是响应读不到 —— 对"删掉一条数据"这类副作用足够用了。

**因此**：① 写接口必须校验 `Origin` 与令牌；② 认证接口显式要求 `Content-Type: application/json`（非简单类型 → 强制预检 → 恶意源拿不到许可）；③ 不要把"我们配了 CORS"当成 CSRF 已解决。

### 9.8 令牌在传输与日志中的约束

| 约束 | 做法 |
|---|---|
| 只走请求头 | `X-CSRF-Token`。**永不**放进 URL / 查询参数（会进访问日志、浏览器历史、`Referer`） |
| 响应体不下发到日志 | `/auth/csrf` 与登录/注册响应体中的令牌属"可重放但需配合会话"的敏感值，按凭据同级处理 |
| 日志过滤清单 | `cookie`、`set-cookie`、`authorization`、**`x-csrf-token`**（v2 新增）四者一律在请求日志中间件里剔除 |
| 缓存 | 所有认证相关响应 `Cache-Control: no-store`；`Vary: Origin` 必须存在，否则共享缓存可能把带 `Access-Control-Allow-Origin` 的响应喂给别的源 |
| 错误信息 | 403 的响应体只有 `{code, message, details: null}`，**不回显收到的令牌、不回显期望值** |

### 9.9 前端接入约定（Phase 5 实施，此处先定契约）

| 约定 | 说明 |
|---|---|
| 存储位置 | **内存变量**（模块级），不放 `localStorage` / `sessionStorage`：两者都会把令牌持久化到磁盘并跨标签页共享，XSS 之外还多一个"本机取证"的面 |
| 取令牌时机 | ① 应用启动后首次需要写操作前；② 登录/注册成功后直接用响应体里的令牌；③ 收到 `csrf_token_expired`/`invalid` 时 |
| 失败重试 | 收到 403 且 `code in (csrf_token_missing, csrf_token_invalid, csrf_token_expired)` → **最多重取一次令牌并重试一次原请求**，仍失败则上报用户。**禁止无限重试**（会变成自我 DoS） |
| 多标签页 | 各标签页独立取令牌，互不影响（令牌无状态，多个并存有效） |
| 并发写 | 同一标签页内的并发写共用同一令牌即可，无需串行化 |

---

## 10. 错误语义与防用户枚举

| 场景 | HTTP | `code` | 响应体是否区分原因 |
|---|---|---|---|
| 未登录访问受保护接口 | 401 | `authentication_required` | 不区分（沿用现有）。**四种成因完全同形**：无 Cookie / 令牌伪造 / 空闲过期 / 绝对过期 / 已撤销 |
| 登录：邮箱不存在 | 401 | `invalid_credentials` | **与密码错逐字节一致**（状态码、`code`、`message`、`details` 结构、响应头） |
| 登录：密码错 | 401 | `invalid_credentials` | 同上 |
| 登录：账号被禁用（将来） | 401 | `invalid_credentials` | 同上（对外不暴露"你被禁用"） |
| 会话过期/已撤销 | 401 | `authentication_required` | 一致；差异只写服务端日志 |
| `Origin` 缺失或不在白名单 | 403 | `origin_not_allowed` | 可区分（这不是账号信息） |
| 缺 `X-CSRF-Token` | 403 | `csrf_token_missing` | 可区分 |
| 令牌结构/签名不符 | 403 | `csrf_token_invalid` | 可区分 |
| 令牌超过 12h 窗口 | 403 | `csrf_token_expired` | 可区分（前端据此重取令牌） |
| 登录限流 | 429 | `too_many_attempts` | 可区分，且带 `Retry-After` |
| 注册：邮箱已存在 | 409 | `email_taken` | **明确告知"该邮箱已注册"**（决策 D3：这是刻意的取舍，见下） |
| 密码不合规 | 422 | `validation_error` | 可区分（属表单校验，不泄漏账号信息）；**响应体不回显用户输入**，见 §10.2 |

**实现要点**：现有 `AppError` → `{code, message, details}` 的结构已经统一（`app/core/errors.py`），新增错误类直接继承即可，不需要改异常处理器。**新增的 `invalid_credentials` 必须写成与 `authentication_required` 结构完全同形**，避免"响应形状不同"成为侧信道。

### 10.1 三个 403/401 的取舍：为什么 CSRF 错误可以"说得清楚"

`Origin` / CSRF 错误可以给出具体原因，因为它们**与账号是否存在无关**。反过来，凡是"原因"能反推出账号信息的（登录失败、找回密码、注册冲突），才必须统一或接受已知泄漏。这条界线比"所有错误都模糊化"更实用：前端需要区分"重取令牌"与"回登录页"，模糊化只会让用户卡住。

### 10.2 422 不能回显输入（容易漏的一处）

FastAPI 默认的 `RequestValidationError` 会把**出错字段的原值**放进 `errors[].input`。对一个"密码太短"的 422，这就把明文密码写进了响应体（进而可能进浏览器控制台、监控上报、错误日志）。

| 要求 | 做法 |
|---|---|
| 认证相关路由注册专用校验异常处理器 | 复制标准结构，但**删除 `input` 与 `ctx`**，只保留 `loc` / `type` / `msg` |
| `details` 里不出现任何请求值 | 用白名单构造：只输出字段名与"为什么不合法"（如 `min_length`） |
| 断言测试 | 发送 `{"password": "short"}` → 422，断言响应全文**不包含** `short` |

### 10.3 "响应时间防枚举"的可测试表述（v2 修正）

v1 写的是"响应耗时都一致"—— **这是无法验收的承诺**。JIT 预热、GC、数据库缓存、CPU 调度都会让两次请求差出几毫秒，任何基于"耗时相等"的断言在 CI 上必然抖动，最后只能被删掉或被 `sleep` 掩盖。

改为两条**确定性**要求 + 一条**信息性**观测：

| 编号 | 要求 | 验收方式 | 性质 |
|---|---|---|---|
| E1 | 登录路径对"邮箱不存在"与"密码错"都**恰好调用一次** Argon2 校验（不存在时对固定的 dummy PHC 串校验） | 单元测试用 spy 统计 `verify_password` 调用次数与参数（断言 `dummy=True` 分支被走到） | **确定性，阻塞** |
| E2 | 两条路径的**代码路径深度一致**：不做"存在则查库、不存在则提前 return"的短路 | 分支覆盖：两条路径都覆盖到"生成 401"的同一函数 | **确定性，阻塞** |
| E3 | 抽样 30 次取**中位数**，两者差值 ≤ 10 ms | `@pytest.mark.timing`，**默认不跑**，只作为手动诊断 | 信息性，不阻塞 CI |

> 说明：E1/E2 保证"攻击者无法通过结构差异区分"，E3 只是"没有明显反常"的体检。把不可靠的统计断言留在默认测试里，只会训练团队忽略红灯。

### 10.4 为什么注册冲突选择"明确告知"（决策 D3）

| 方案 | 好处 | 代价 | 是否采用 |
|---|---|---|---|
| `409 email_taken` | 用户知道"该去登录/找回密码"，不会被卡在"注册没反应" | 泄漏"该邮箱注册过" | ✅ **采用** |
| 统一 `202 已发送邮件` | 不泄漏存在性 | 没有邮件通道 → 只能**假装**发了信，用户永远等不到邮件，等于骗人 | ❌ |
| 静默 `201` 但什么也不做 | 不泄漏 | 更糟：用户以为自己注册成功，下次登录必然失败 | ❌ |

代价的补偿措施：① 注册限流 5 次/小时/IP，把枚举成本抬高；② `email_taken` 的响应**不区分**"邮箱存在但账号被禁用"等内部状态；③ 该泄漏面已在 §3.4 U9 与本节显式记录，属于**知情接受**而非疏漏。真正的根治是等有邮件通道后改成"注册即发验证邮件 + 统一 202"，届时只需换这一处的返回。

---

## 11. 限流与暴力破解

### 11.1 部署假设（先承认边界，再谈策略）

| 项 | 本阶段假设 | 含义 |
|---|---|---|
| 部署形态 | **单实例、单 worker**（`uvicorn --workers 1`） | 进程内计数器是**唯一**计数源，此时"全局一致"恰好等价于"进程内一致" |
| 计数存放 | 进程内字典（按 key 的滑动窗口） | 重启即清零；进程崩溃丢计数（可接受：崩溃本身已经中断了攻击） |
| 多 worker（`--workers 4`） | ⚠️ **每个 worker 各有一份计数** | 实际允许次数 = 配置值 × worker 数；失败退避也各自独立，攻击者可轮换连接命中不同 worker |
| 多实例 / 反向代理后的多副本 | ⚠️ **完全不共享** | 上述倍数进一步放大，且**没有**任何跨实例协调 |
| 验收标准 | **以单实例、单 worker 跑通全部限流测试** | 不得声称"多实例下限流有效" |

> 这不是"以后再说"的免责声明，而是**验收边界**：Phase 3 的"限流有测试"只对单进程成立。文档里必须写清，避免未来有人看到"限流已实现"就以为可以直接横向扩容。

### 11.2 为将来换存储留缝（现在不实现 Redis）

```
RateLimiter (Protocol)
  ├─ hit(key: str, *, limit: int, window: timedelta) -> Decision   # 允许/拒绝 + 剩余配额 + 重试秒数
  └─ reset(key: str) -> None                                       # 登录成功后清零失败计数

MemoryRateLimiter   ← 本阶段实现，进程内
RedisRateLimiter    ← 将来：只换依赖注入的一行，路由与服务代码不改
```

| 约束 | 理由 |
|---|---|
| 路由不直接 import 具体实现，只依赖 `RateLimiter` 协议（FastAPI `Depends` 注入） | 换后端时不动业务代码 |
| `Decision` 是纯数据（`allowed` / `retry_after` / `remaining`） | 测试可直接断言，不需要真正 sleep |
| 时钟从外部注入（`clock: Callable[[], float]`） | 退避与窗口都能用假时钟测试，避免测试里 sleep |
| key 的构造集中在一个函数（`login:acct:<email_hash>`、`login:ip:<ip>`、`register:ip:<ip>`、`global:ip:<ip>`） | 避免每个路由自己拼 key 导致口径不一致 |

### 11.3 策略

| 维度 | 策略 | 说明 |
|---|---|---|
| 登录：按账号 | 连续失败 5 次 → 指数退避（1s, 2s, 4s… 上限 5 分钟），15 分钟无失败则清零 | 计数 key 用**邮箱哈希**，不存明文邮箱 |
| 登录：按 IP | 10 次/分钟 | 防"同一 IP 撞很多账号" |
| 注册 | 5 次/小时/IP | 防批量抢注（开放注册的直接后果，见 §18.3） |
| `/auth/csrf` | 60 次/小时/会话 | 该接口计算量小，但它是"取令牌"入口，需防脚本刷日志 |
| 全局 | 每 IP 300 请求/分钟 | 基础保护，挡住明显的脚本 |
| 响应 | 429 + `Retry-After`（秒） | 明确告知何时可重试，避免客户端疯狂重试 |
| 失败路径 | 在**同一时间预算**内返回 | 不退避反而更快响应会变成"账号存在"的信号；与 §10.3 的 E1/E2 配合 |

**明确不做的**：不做"失败 N 次永久锁定账号" —— 那会变成攻击者用来锁死他人账号的武器（DoS 转向用户）。也不做"按 IP 封禁"，理由相同（NAT / 运营商级 NAT 下会误伤整片用户）。

### 11.4 限流必须有的测试（否则等于没做）

| 用例 | 断言 |
|---|---|
| 同账号连续 5 次密码错 → 第 6 次 | 429 + `Retry-After` ∈ (0, 301]；且 5 次错误的响应体完全一致（不漏"还剩几次"） |
| 退避序列 | 假时钟推进，断言允许重试的时刻依次为 +1s / +2s / +4s，封顶 300s |
| 15 分钟无失败后清零 | 假时钟推进 901s，第 6 次恢复为 401（不是 429） |
| 同 IP 不同账号 | 第 11 次/分钟内 → 429（按 IP 维度独立生效） |
| 注册 5 次/小时后第 6 次 | 429（即使邮箱都不同） |
| 登录成功 | 清零该账号的失败计数（否则"改对密码后仍被退避"） |
| 429 是否泄漏账号存在性 | 未注册邮箱同样会触发 429（按 IP 维度），不因账号不存在而豁免 |
| 多 worker 行为 | **不做断言**，但在测试注释与文档里标注"本测试仅对单 worker 有效" |

**仍然存在的风险**：攻击者用大量分布式 IP（僵尸网络）时，按 IP 的限流失效；按账号的退避仍有效。这是本项目能接受的上限（无 CAPTCHA、无设备指纹，均超出 Phase 3 范围）。

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
| 删号（将来） | `event=user.deleted`, `user.public_id`, 级联删除的行数 | 邮箱、密码哈希 |

**中间件要求**：请求日志必须显式排除 `cookie` / `set-cookie` / `authorization` / **`x-csrf-token`** 四个头。Phase 2.7 已实测应用日志会把 DSN 密码段掩码成 `***`，这条纪律要延续到请求头。

### 12.1 禁止进入日志 / 错误响应 / 审计事件的清单（复审问题 6）

| 类别 | 具体值 | 为什么连"哈希后 8 位"都不行 |
|---|---|---|
| 密码 | 明文、任何形式的截断、`repr` | 用户常复用密码，截断片段也会削弱撞库防护 |
| 会话令牌 | 原始 43 字符串、其 SHA-256、Cookie 原始头 | 原始串 = 直接登录；哈希 = 可离线比对 |
| CSRF 令牌 | `X-CSRF-Token` 值、响应体中的 `csrf_token` | 与有效会话 Cookie 配合即可发起写请求；日志往往比库更容易被读到 |
| Cookie | 整个 `Cookie` / `Set-Cookie` 头 | 里面就是会话令牌 |
| 邮箱 | 完整地址 | 属个人数据；用 `SHA-256(email)[:8]` 关联同账号尝试即可 |
| 密码哈希 | PHC 串 | 可离线爆破（虽是慢哈希，但没必要给） |

**统一做法**：日志与错误都过同一个 `redact()`；`redact()` 的单元测试用**真实的字段名与真实长度的假值**断言输出中不出现这些子串。测试里用 `caplog` 全量抓取，断言 `assert "wm_" not in text` 之类**基于值**的检查（而不是"检查代码里有没有 print"）。

### 12.2 账号删除、会话级联与日志保留（复审问题 III.4）

这三者的目标互相冲突，必须显式取舍：

| 对象 | 删号时的行为 | 理由 |
|---|---|---|
| `items` | `ON DELETE CASCADE` 物理删除 | 用户数据必须真的消失 |
| `auth_identities` | `ON DELETE CASCADE` 物理删除 | 删凭据 |
| `sessions` | `ON DELETE CASCADE` 物理删除 | 删号即全端下线 |
| 结构化审计日志（stdout / 将来的日志系统） | **不删除**，且**无法**删除 | 日志是追加写的，且已离开进程；承诺"删号即抹掉日志"是做不到的 |
| 日志里的标识 | 只有 `public_id`（随机 UUID）与邮箱哈希前 8 位 | 无 `public_id` → 用户映射时，日志不可反查到人 |

**因此必须承认**：删号 ≠ "所有痕迹消失"。可承诺的是"**业务数据与凭据立即物理删除；日志中的伪匿名标识按保留期（建议 30 天）自然滚掉**"。这个表述要写进用户可见的说明，不要写成"彻底删除所有数据"。

> 本阶段**不实现**删号接口（§19），此处只定语义。将来实现时必须同时做到：① 单事务级联；② 删除前撤销所有会话；③ 记录 `user.deleted` 事件但**不含**邮箱。

---

## 13. 开发身份与认证：分环境的行为矩阵（v2 重写）

现状已有一层保护（`Settings` 构造期拒绝 `production + dev_user_enabled`），Phase 3 要再加两道：

| 层 | 措施 |
|---|---|
| 配置层 | **保持现状**：`APP_ENV=production` + `DEV_USER_ENABLED=true` → 启动即失败（`ValueError`），补回归测试锁死 |
| 解析层 | **先解析会话；只有在"完全没有会话 Cookie"时，才允许回落到开发身份**（且仍需三重环境门禁） |
| 输出层 | `/health` 与启动日志暴露 `auth_mode`（`session` / `development_identity` / `unauthenticated`），让"当前到底是什么模式"永远可见 |
| 测试层 | 见下表；`APP_ENV=test` 下开发身份**默认关闭**，需要时用显式 fixture 打开 |

> 设计取舍：**保留**开发身份而不是删掉。理由：Phase 4/5 要写上传与前端，每次调试都真登录一遍会显著拖慢；而它的风险已被三重门禁压到"配置写错才可能触发"，且 `production` 下启动即失败，不是静默放行。

### 13.1 必须修正的一个错误结论

v1 的测试矩阵第一行写的是「无 Cookie 调 `/items` → 全部 401」，并把它当成普遍结论。**这在开发身份开启时不成立**：

| 配置 | 无 Cookie 的 `GET /items` | v1 的说法 |
|---|---|---|
| `APP_ENV=development` + `DEV_USER_ENABLED=true` + `DEV_USER_PUBLIC_ID` 有效 | **200**（以开发身份返回该用户的衣物） | ❌ 说成 401 |
| 其他任何配置 | 401 | ✅ |

所以断言必须**按环境分开写**，不能写成一句"没有 Cookie 必然 401"。

### 13.2 环境 × 凭据 完整矩阵

四种环境：**D**（development + 开发身份启用）、**N**（development/test 但开发身份关闭）、**T**（pytest 测试环境）、**P**（production）。

| # | 环境 | 请求携带 | 受保护接口（`/items`）期望 | `auth_mode` | 关键理由 |
|---|---|---|---|---|---|
| 1 | D | 无 Cookie | **200**，`user_id` = `DEV_USER_PUBLIC_ID` 对应者 | `development_identity` | 开发便利，唯一允许"无凭据即身份"的分支 |
| 2 | D | 合法会话 Cookie | **200**，按该会话的用户 | `session` | 会话优先于开发身份（不能让开发身份覆盖真实登录） |
| 3 | D | **无效** Cookie（伪造/过期/已撤销） | **401**，并附清除 Cookie | `unauthenticated` | **不回落**到开发身份：回落会让"带坏 Cookie"变成"静默换身份"，掩盖真实故障 |
| 4 | D | 有效 Cookie，但 CSRF 缺失（写请求） | **403**（先 401 才轮到 403 的判断也成立，见 §7.3） | `session` | 开发身份不能豁免 CSRF |
| 5 | N | 无 Cookie | **401** `authentication_required` | `unauthenticated` | 这就是 v1 那条结论真正适用的范围 |
| 6 | N | 合法会话 Cookie | **200** | `session` | 认证路径在开发环境同样要能测 |
| 7 | T（pytest 默认） | 任意 | 由 fixture 显式注入会话或开关开发身份；**默认等价于 N** | — | 避免测试"碰巧因为开发身份而通过" |
| 8 | P + `DEV_USER_ENABLED=true` | 任意 | **进程启动失败**（`ValueError`），请求永远到不了路由 | — | 配置层拦截，不是请求层 |
| 9 | P | 无 Cookie | 401 | `unauthenticated` | — |
| 10 | P | 伪造/过期/已撤销 Cookie | 401 | `unauthenticated` | 四种成因同形（§10） |
| 11 | P | 携带任何"开发身份相关"的请求头 / 查询参数 | 401（**完全不读取**） | — | 身份只从会话来；请求里自报的标识一律不采信（§2 铁律） |

### 13.3 Cookie 状态细分（都应是 401，且响应逐字节一致）

| Cookie 状态 | HTTP | 清除 Cookie | 服务端日志 |
|---|---|---|---|
| 缺失 | 401 | 否（本来就没有） | `auth.session.absent` |
| 格式非法（长度≠43、含非法字符） | 401 | ✅ | `auth.session.malformed` |
| 未知令牌（哈希查不到） | 401 | ✅ | `auth.session.unknown` |
| 空闲过期（`now - last_seen_at ≥ 7d`） | 401 | ✅ | `auth.session.idle_expired` |
| 绝对过期（`now ≥ absolute_expires_at`） | 401 | ✅ | `auth.session.absolute_expired` |
| 已撤销（退出） | 401 | ✅ | `auth.session.revoked(logout)` |
| 已撤销（改密被踢） | 401 | ✅ | `auth.session.revoked(password_change)` |

> "逐字节一致"指**响应体**与状态码；`Set-Cookie` 是否存在会有差异（缺失时不必发清除指令）。这不算侧信道：攻击者本来就不知道对方的 Cookie 状态。

### 13.4 必须有的回归测试（锁死行为，防止将来"顺手"放宽）

| 用例 | 断言 |
|---|---|
| `Settings(app_env="production", dev_user_enabled=True)` | 抛 `ValueError`（构造期） |
| 环境 D 无 Cookie | 200（**明确断言这是有意为之**，与第 5 行形成对照） |
| 环境 D 带坏 Cookie | 401，**不是** 200 |
| 环境 N 无 Cookie | 401 |
| 生产环境 + 任意 Cookie | 401，且日志 `auth_mode=unauthenticated` |
| `/health` | 始终 200，三种 `auth_mode` 都能被读到 |

---

## 14. 接口清单（设计）

| 方法 | 路径 | 认证 | `Origin` | CSRF 令牌 | 说明 |
|---|---|---|---|---|---|
| `POST` | `/api/v1/auth/register` | 否 | ✅ | ❌（§9.5） | 建 `users` + `auth_identities`，**自动登录**（D5）；冲突 → `409 email_taken`（D3）；5 次/小时/IP；**响应体含会话绑定的 `csrf_token`** |
| `POST` | `/api/v1/auth/login` | 否 | ✅ | ❌（§9.5） | 统一 401；**响应体含 `csrf_token`**；10 次/分/IP + 账号退避 |
| `GET` | `/api/v1/auth/csrf` | 是 | — | — | 返回 `{csrf_token, expires_in}`；`no-store`；60 次/小时/会话 |
| `POST` | `/api/v1/auth/logout` | 可选 | ✅ | 有会话时 ✅ | 撤销当前会话 + 清 Cookie。**幂等**：无有效会话也返回 204 |
| `GET` | `/api/v1/auth/me` | 是 | — | — | `public_id` / `display_name` / 邮箱（脱敏显示可选） |
| `GET` | `/api/v1/auth/sessions` | 是 | — | — | 本人活跃会话（`id` / `issued_at` / `last_seen_at` / `user_agent`） |
| `DELETE` | `/api/v1/auth/sessions/{id}` | 是 | ✅ | ✅ | 只能撤自己的，别人的 → 404（不 403，避免泄漏 id 存在性） |
| `POST` | `/api/v1/auth/password` | 是 | ✅ | ✅ | 改密（需当前密码）→ 撤销其他会话，当前会话保留 |

> 完整的"哪个接口要什么"以 §9.6 的矩阵为准，本表只是索引；两处若冲突，以 §9.6 为准并修正本表。

**不新增的**：`/auth/forgot-password`、`/auth/reset-password`、`/auth/verify-email` —— 都需要邮件通道，当前没有。**也没有** `/auth/delete-account`（§19）。

**现有接口的变化**：`/api/v1/items/*` **零改动**。它们已通过 `UserContextDep` 取身份，认证接入后自动受保护；CSRF 与 `Origin` 校验在**依赖层**统一施加，不落到每个路由上。

---

## 15. 实施任务拆分（审核通过后才动手）

| 编号 | 任务 | 主要产出 | 依赖 |
|---|---|---|---|
| T1 | 依赖与密码哈希工具 | `argon2-cffi`；`app/core/security.py`：`hash_password` / `verify_password` / `needs_rehash` / `dummy_verify`；**实测单次耗时 + 并发峰值内存**，据此定参并定 `AUTH_HASH_CONCURRENCY`（§8.1）；`normalize_email()` / `validate_email_shape()` | — |
| T2 | 数据模型 | `AuthIdentity` / `Session` 模型 + Alembic 迁移（`revoked_reason` 六个取值、`UNIQUE(provider,subject)`、`UNIQUE(token_hash)`；含 `upgrade`/`downgrade`） | T1 |
| T3 | 会话服务 | `app/services/session_service.py`：`issue` / `resolve`（四判据写在 SQL 里）/ `revoke` / `revoke_others` / `renew`（**条件 UPDATE 返回 rowcount**）/ `purge_expired`；令牌生成与 `SHA-256` | T2 |
| T4 | 认证路由 | `app/api/v1/routes/auth.py` + schemas（`extra="forbid"`，认证路由专用 422 处理器去掉 `input`）+ **`GET /auth/csrf`**；登录/注册响应体带 `csrf_token` | T3 |
| T5 | 统一错误与防枚举 | `InvalidCredentials` / `EmailTaken`（捕获 `IntegrityError` 转 409，整事务回滚）/ `OriginNotAllowed` / `CsrfTokenMissing` / `CsrfTokenInvalid` / `CsrfTokenExpired` / `TooManyAttempts`；登录两条路径的 E1/E2 可测化 | T4 |
| T6 | 限流 | `RateLimiter` 协议 + `MemoryRateLimiter`（滑动窗口 + 退避，**时钟注入**）+ `Depends` 注入 + key 构造集中 | T4 |
| T7 | 身份接入 | 改 `resolve_user_context`：**先会话、后开发身份**（仅"无 Cookie"时回落）；`UserContext` 增可选 `session_id`；`auth_mode` 三值 | T3, T4 |
| T8 | CSRF 令牌与来源校验 | 令牌生成/校验纯函数（HMAC，key = `token_hash`）；`require_origin` 依赖；`require_csrf` 依赖；按 §9.6 矩阵挂载；CORS 显式配置（含 `Vary: Origin`、`no-store`） | T3, T4 |
| T9 | 审计与日志脱敏 | `redact()` 统一入口（四个头 + 令牌 + 邮箱）；结构化事件；聚合与 401/403 的成因区分只进日志 | T7 |
| T10 | 测试 | 见 §16；含限流、CSRF、矩阵、脱敏四组 | 全部 |

**顺序理由**：T1 先做是因为要先量出哈希的**耗时与并发内存**在目标机器上的实际值（机器的 CPU/内存决定参数），否则参数是拍脑袋的。T7 放后面是为了让认证逻辑先独立可测，再接进现有依赖链 —— 避免一上来就改动 104 项测试都依赖的入口。**T8 的令牌函数是纯函数，实际编码宜在 T4 之前先落地**（`/auth/csrf` 与登录响应都要用到），但**挂载到全局依赖**必须在 T4 的路由稳定之后，这样"谁需要令牌"由矩阵统一决定，而不是散落在各路由里。

---

## 16. 测试矩阵（对应路线图验收项，v2 重写）

### 16.1 认证与身份

| 路线图验收项 | 测试用例 |
|---|---|
| 未登录不能访问受保护接口 | **分环境**（§13.2）：环境 N / P 无 Cookie → 401；**环境 D 无 Cookie → 200**（有意为之，必须显式断言，避免将来被误改成 401 或反之）；`/health` 始终 200 |
| 篡改 `user_id` / `public_id` 不能跨用户 | 请求体塞 `user_id`/`public_id` → 422（`extra="forbid"`）；A 的会话拿 B 的 `item_id` → 404；A 的会话 `PATCH`/`DELETE` B 的 item → 404 |
| 篡改 Cookie 不能越权 | 随机令牌 / 改一个字符 / 空值 / 长度 42 或 44 / 含 `=` 填充 → 全部 401 且响应体一致 |
| 令牌四种失效 | 空闲过期 / 绝对过期 / 退出撤销 / 改密撤销 → 均 401；**日志中的成因不同、响应中相同** |
| 登录有测试 | 正确凭据 → 200 + `Set-Cookie`（`HttpOnly` 断言用 `Set-Cookie` 原文，客户端读不到）+ 响应体含 `csrf_token`；错误密码 → 401；不存在邮箱 → 与错误密码**响应体逐字节相同** |
| 退出有测试 | 退出后同一 Cookie 再请求 → 401；重复退出 → 204（幂等）；**无会话退出 → 204 且不需要 CSRF** |
| 过期/撤销有测试 | 改密后其他会话 401、当前会话 200；`DELETE /auth/sessions/{id}` 只能撤自己的；撤别人的 → 404 |
| 会话固定 | 登录前手工塞一个 Cookie → 登录后返回的是**不同**令牌；登录流程不读取任何客户端提供的会话标识 |
| 密码不落日志 | `caplog` 全量抓取，断言不含明文密码、不含令牌原文、不含 `csrf_token` 值 |
| 开发快捷方式不在生产生效 | `Settings(app_env="production", dev_user_enabled=True)` → `ValueError`；且该情形下**进程根本没起来**，不存在"请求级兜底" |

### 16.2 CSRF 与来源

| 场景 | 断言 |
|---|---|
| 写请求缺 `Origin` | 403 `origin_not_allowed` |
| `Origin` 在白名单外（含同站子域） | 403 `origin_not_allowed` |
| 有会话、写请求缺 `X-CSRF-Token` | 403 `csrf_token_missing` |
| 令牌结构损坏（少一段、非 base64url、长度不符） | 403 `csrf_token_invalid` |
| 令牌签名不符（拿别的会话的令牌） | 403 `csrf_token_invalid` |
| 令牌超过 12h（假时钟） | 403 `csrf_token_expired` |
| 用 A 的令牌 + B 的 Cookie | 403 `csrf_token_invalid` |
| 只带令牌、不带 Cookie | 401（**不是** 403，也不是 200） |
| 令牌放查询参数而非头 | 服务端不读取（写请求仍 403 `csrf_token_missing`） |
| `GET /auth/csrf` 无会话 | 401 |
| `GET /auth/csrf` 有会话 | 200，`Cache-Control: no-store`，`Vary: Origin` 存在；连续两次调用返回**不同**令牌但**都有效**（多标签页前提） |
| 登录/注册不带 CSRF 令牌 | 成功（这是设计，不是漏洞），但缺 `Origin` → 403 |
| `Content-Type: text/plain` 的登录请求 | 415 或 422（明确拒绝非 JSON），不执行认证逻辑 |
| 401 与 403 的先后 | 无会话 + 无令牌 → 401；有会话 + 无令牌 → 403 |

### 16.3 滑动续期（§7.2 的逐条验收）

| 场景 | 断言 |
|---|---|
| 5 分钟内连发 10 个请求 | `last_seen_at` **只变一次**；`Set-Cookie` **只出现一次** |
| 超过 5 分钟再发请求 | `last_seen_at` 前移，且**该响应**带 `Set-Cookie`，`Max-Age=604800` |
| 条件更新未命中（`rowcount=0`） | **一定没有** `Set-Cookie`（这是"两个时钟同步"的核心断言） |
| 会话临近绝对过期（假时钟设到第 29.5 天） | `Max-Age ≈ 43200`（半天），而不是 604800 |
| CSRF 校验失败的写请求 | 不续期（`last_seen_at` 不变、无 `Set-Cookie`） |
| 401 请求 | 不续期，且带清除 Cookie |
| 并发 6 个请求（线程或 `asyncio.gather`） | `last_seen_at` 最多前移一次；无死锁；无 500 |
| 撤销与续期并发 | 撤销后 `rowcount=0`，会话不再续期 |

### 16.4 限流（§11.4）

见 §11.4 的表格，用例一一对应；全部用**假时钟**，测试里不出现 `sleep`。

### 16.5 其他

| 项 | 断言 |
|---|---|
| 422 不回显输入 | `{"password":"short"}` → 响应全文不含 `short` |
| CORS | 预检请求（`OPTIONS`）对白名单外来源不返回 `Access-Control-Allow-Origin`；带凭据时不返回 `*` |
| 迁移往返 | `alembic upgrade head` → `downgrade -1` → `upgrade head` 均成功，且 `items` 数据不受影响 |
| 现有 104 项测试 | 全部保持通过（`UserContext` 只加可选字段，构造调用不受影响） |

**测试隔离**：沿用 Phase 2 的外层事务 + `Session(bind=connection)` 方案（`join_transaction_mode=conditional_savepoint`），保证测试零残留。新增表加入清理与 `TRUNCATE` 顺序；**唯一约束相关的测试必须真的走到 `IntegrityError`**（不能只测应用层分支），否则并发那条结论没被验证。

**测试环境变量**：`APP_ENV=test` 且 `DEV_USER_ENABLED` **默认 false**；需要开发身份的用例用显式 fixture 打开。这一点是 v2 修正的重点 —— 若测试默认开着开发身份，几乎所有"未登录 → 401"的断言都会因为走错分支而变成假通过。

---

## 17. 兼容性 / 明确不改动的部分

| 对象 | 是否改动 | 说明 |
|---|---|---|
| `UserContext` | **仅加一个可选字段** `session_id: int \| None = None` | 现有构造调用（含测试）不受影响 |
| `ItemRepository` | ❌ 不改 | 隔离逻辑已正确，认证只是让 `UserContext` 来源变了 |
| `items` 路由与 schemas | ❌ 不改 | 自动受保护 |
| `errors.py` 异常处理器 | ❌ 不改 | 新增错误类继承 `AppError` 即可 |
| `config.py` 开发身份门禁 | ❌ 不改 | 保留，补测试 |
| 配置项 | ✅ 新增 3 个**有默认值**的项：`SESSION_IDLE_TIMEOUT`(7d) / `SESSION_ABSOLUTE_TIMEOUT`(30d) / `AUTH_HASH_CONCURRENCY`(4)；`COOKIE_SECURE` / `COOKIE_NAME_PREFIX` 沿用 D7 的规划 | **不新增必须人工填写的密钥**（CSRF 令牌复用会话令牌哈希作 key），因此现有 `.env` 无需修改即可启动 |
| `sessions` / `auth_identities` | ✅ 新增 | 一次迁移 |
| 迁移 | ✅ 新增 1 个 revision | 需验证 `upgrade` → `downgrade` → `upgrade` 往返 |

---

## 18. 决策记录（**已于 2026-10-25 确认，不再阻塞**）

### 18.1 你已明确拍板的（D1–D3）

| # | 决策 | 结论 | 对实现的影响 |
|---|---|---|---|
| **D1** | 用户模型 | **多用户**，**开放注册**（无邀请码、无首用户锁定） | 注册接口对公网开放；`users` 表不再假设"只有一行"；不需要 bootstrap 首个账号的特殊逻辑 |
| **D2** | 会话时长 | **空闲 7 天 / 绝对 30 天** | `idle_expires_at = last_seen_at + 7d`；`absolute_expires_at = issued_at + 30d`；Cookie `Max-Age` 取 7 天，靠滑动续期延长 |
| **D3** | 注册时邮箱已存在 | **`409 email_taken`，明确告知**（+ 限流补偿） | 见 §10 末尾的取舍表；`email_verified` 保持 `false` 且不阻塞登录 |

### 18.2 未单独回复的项（按建议默认落地，如需改现在说）

| # | 问题 | 默认取值 | 改起来的成本 |
|---|---|---|---|
| D4 | 密码策略 | **≥12 字符**，不强制大小写/符号组合（NIST 基线）；拒绝常见弱口令与"与邮箱相同" | 低（一个校验函数） |
| D5 | 注册后是否自动登录 | **自动登录**（直接下发会话 Cookie） | 低 |
| D6 | 设备管理页面 | 本阶段**只做后端接口**（`GET/DELETE /auth/sessions`），UI 留到 Phase 5 | 低 |
| D7 | 生产域名与 HTTPS | **暂不部署生产**。`COOKIE_SECURE` / `COOKIE_NAME_PREFIX` 做成配置项：开发（`http://localhost`）用 `wm_session` + 非 `Secure`；上线时切 `__Host-wm_session` + `Secure` | 低（配置位已预留，见 §9.1） |

> D7 的隐含结论：Phase 3 交付物只在 `localhost` 验证，**不能**把它当成"已在公网安全运行"。真正上线前必须补：固定域名、TLS 证书、`COOKIE_SECURE=true`、CORS 白名单换真实域名、限流从进程内换 Redis（多实例）。这些已写进 §19 与本表，不会被遗忘。

### 18.3 开放注册带来的三条额外要求（D1 的直接后果）

1. **注册必须比登录更严地限流**（5 次/小时/IP）：登录爆破只害一个账号，批量注册会灌爆 `users` 表。
2. **邮箱规范化必须是唯一入口**：`normalize_email()` = `strip().lower()`，注册、登录、改密三处都走它，否则 `A@x.com` 与 `a@x.com` 会绕过唯一约束变成两个账号。
3. **唯一冲突要映射成业务错误而不是 500**：`uq_auth_identities_provider_subject` 触发的 `IntegrityError` 必须在服务层捕获并转 `409 email_taken`；**不能**先 `SELECT` 再 `INSERT`（并发下会双写成功，靠数据库约束兜底才是对的）。

---

## 19. 本轮明确不做

- 找回密码 / 重置密码 / 邮箱验证（缺邮件通道）—— 注意这是**硬限制**，见 §6.5
- OAuth / OIDC / Passkey（已在 §4 说明为后续增强）
- 双因素认证（TOTP / WebAuthn）
- 多实例共享限流（换 Redis）
- 非浏览器 API 客户端认证面（`Authorization: Bearer`）—— 见 §9.6
- 账号删除接口（只定语义，见 §12.2）
- 用户资料（身高、体型、风格偏好）
- 任何前端登录页 —— 本阶段只做后端，Phase 5 接 UI
- 图片上传与隐私外发策略（Phase 4）
- 审计日志的持久化与查询界面（先写结构化日志）
- 生产部署、域名与 TLS 配置（D7：本阶段只在 `localhost` 验证，`Secure` / `__Host-` 前缀留配置位、不启用）
- 会话表的历史清理定时任务（只留 `purge_expired` 接口）

### 19.1 计划中的 runbook（**本轮不创建文件**）

拟新增 `docs/runbooks/auth-cookie-policy.md`，内容规划：

| 章节 | 内容 |
|---|---|
| 1. Cookie 清单 | 只有一个 `wm_session` / `__Host-wm_session`；各属性取值与理由；为什么没有 CSRF Cookie |
| 2. 双时钟 | `last_seen_at` 与 `Max-Age` 的同步规则（§7.2 的运维视角版本）、排障时的三个检查点 |
| 3. 环境差异 | `localhost` 双端口 vs 生产双子域；`Secure` / `__Host-` 切换步骤；CORS 白名单怎么填 |
| 4. CSRF 客户端接入 | 取令牌时机、内存存储、403 后只重试一次、多标签页行为 |
| 5. 故障对照表 | 401/403 各 `code` 的含义、前端该做什么、服务端日志该看哪条 |
| 6. 上线检查清单 | TLS、`COOKIE_SECURE=true`、`Origin` 白名单用真实域名、`Vary: Origin`、`no-store`、限流形态（单实例假设是否仍成立） |
| 7. 禁止事项 | 不要给 Cookie 设 `Domain`；不要把令牌放 URL；不要用 `X-Requested-With` 当防护；不要在多 worker 下声称限流有效 |

---

## 20. 决策状态与下一步

| 事项 | 状态 |
|---|---|
| 方案 A（服务端会话 + `HttpOnly` Cookie，不用 JWT） | ✅ 未提异议，且 D2 的"空闲/绝对双超时 + 可撤销"只有在服务端会话下才成立 → **按此实施** |
| §18 D1–D3（多用户开放注册 / 7 天+30 天 / 409 `email_taken`） | ✅ **已拍板**（2026-10-25） |
| §18 D4–D7（密码策略 / 自动登录 / 设备页 / 生产 HTTPS） | 🟡 按默认值实施，可随时推翻（成本都低） |
| CSRF 承载方式（v2 修订） | ✅ **已改**：响应体下发 + 会话绑定 HMAC；删除 `wm_csrf` Cookie；新增 `GET /auth/csrf` |
| 接口形状 | ✅ 已随 v2 更新（§14 / §9.6） |
| 安全复审 | ✅ v2 已完成五类问题的修订，见 `docs/planning/phase3-auth-design-review.md` |

**下一步**：按 §15 的 T1 → T10 顺序实施，每个任务完成后跑全量测试（当前基线 104 项）并**单独提交**，不推送。开工前先做 T1 的哈希**耗时 + 并发内存**实测，用实测值定 Argon2id 参数与并发上限。

**仍然阻塞开工的两件事**（都需要你一句话）：

1. **是否现在开写 T1**：会新增 `argon2-cffi` 依赖并产生第一次迁移，属实质代码改动。
2. **4 个未推送提交是否先推**（`5d6bdd0` / `e90b8f6` / `91db427` / `fa6d1d3`）：建议先推，避免认证代码的提交与这批文档混在一起推。

> 另需你决定（不阻塞 T1，但会影响 Phase 3 验收口径）：**Phase 3 是否只按"单实例单 worker"验收**（§11.1）。如果预期很快要上多 worker，限流与 `AUTH_HASH_CONCURRENCY` 的设计都要提前调整。
