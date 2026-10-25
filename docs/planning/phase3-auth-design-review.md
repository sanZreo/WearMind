# Phase 3 认证设计安全复审报告

- 日期：2026-10-25
- 复审对象：`docs/design/phase3-auth-design.md`（v1 → v2）
- 复审范围：**仅文档**。未改代码、未装依赖、未建迁移、未动数据库、未改环境变量、未提交、未推送。
- 结论：**五个问题全部修订完成**；文档内部一致性已同步（不是"文末打补丁"）。建议在两项前置条件满足后开始 T1。

---

## 1. 修订了哪些章节

| 章节 | 性质 | 修订内容 |
|---|---|---|
| 文档头 / §0 | 重写 | 版本改 v2；结论句改为"`Origin` + 会话绑定 HMAC 令牌"，删掉"CSRF 双重防御"这一与实际形态不符的说法 |
| §1.1 | **新增论证** | 补"为什么 v1 的 CSRF 方案在生产形态下不成立"：跨源读不到 API 子域 Cookie；并否决"父域 Cookie"这条看似简单的解法 |
| §3.4 U5 / U6 / **U6b** | 改 + 新增 | U5/U6 的对抗项改为 `Origin` + 会话绑定令牌 + JSON 预检；新增 **U6b Login CSRF**（诱导受害者登入攻击者账号） |
| §3.4 U7 | 改 | 承认 XSS 能读到内存中的 CSRF 令牌，说明为何这不构成额外损失 |
| §3.3 表头 | 修正 | "§14 任务" → "§15 任务"（原交叉引用错误） |
| §4.2 / §4.3 | 保留 | 方案比较与"不用 JWT / OAuth / Passkey"的论证**未改**；仅在 §0 与 §5 补一句"零密钥"仍成立的原因 |
| §5 | 重写 | 登录/取令牌/写请求的三段流程，明确步骤顺序（Origin → 会话 → CSRF → 续期） |
| §6.3 | 改 | `revoked_reason` 增加 `idle_expired` / `absolute_expired`；**明确不建 CSRF 列** |
| §6.4 | **新增** | 邮箱规范化 / 格式校验 / 唯一约束 / 并发注册的完整链路与 TOCTOU 说明 |
| §6.5 | **新增** | `email_verified=false` 的三条硬限制与"忘密码即永久丢失"的明确表述 |
| §7 | 重写为 7.1–7.4 | 令牌字节级规则；滑动续期双时钟；请求内事件顺序；并发与撤销边界 |
| §8.1 | **新增** | Argon2id 的**并发内存**成本、信号量上限、队列 DoS |
| §9 | 大半重写 | 只留一个 Cookie；CSRF 全新设计（9.3–9.5）；接口级矩阵（9.6）；CORS≠CSRF（9.7）；传输与日志约束（9.8）；前端契约（9.9） |
| §10 | 改 | 错误码拆到 3 个 CSRF 子码 + `origin_not_allowed`；新增 10.2（422 不回显输入）、10.3（**可测试的**等时表述） |
| §11 | 重写为 11.1–11.4 | 单实例验收边界；`RateLimiter` 协议；策略表；限流测试清单 |
| §12 | 扩充 | 新增 12.1 禁止入日志清单、12.2 删号/级联/日志保留的取舍 |
| §13 | **重写为 13.1–13.4** | 明确"无 Cookie 必然 401"是错结论；环境×凭据矩阵；Cookie 状态细分；回归锁 |
| §14 | 改 | 加 `GET /auth/csrf`；每行加 `Origin` / CSRF 两列 |
| §15 | 改 | T1 加并发内存实测；T2 加六个 `revoked_reason`；T3 加 `renew`；T4 加 `/auth/csrf`；T5/T8 重定义；顺序理由补 T8 的位置 |
| §16 | **重写为 16.1–16.5** | 按环境分组；CSRF 14 条；续期 8 条；限流引用 11.4；测试环境变量默认值 |
| §17 | 改 | 新增"配置项"行：只加**有默认值**的项，不加必须人工填的密钥 |
| §18 | 微调 | D7 的交叉引用修正；D1–D3 内容未变 |
| §19 | 扩充 | 新增"非浏览器 API 客户端""删号接口""会话历史清理"；新增 **19.1 runbook 计划内容（未创建文件）** |
| §20 | 改 | 记录 CSRF 承载方式已变更；列出两项开工前置条件 + 一项验收口径待确认 |

---

## 2. 五个主要问题分别如何解决

### 问题 1：CSRF Token 的跨源可用性

**选的方案**：A（初始化接口在响应体返回令牌，前端存内存，请求时回填 `X-CSRF-Token`）。

**为什么不选 B（Next.js 服务端代理）**：代理确实能把"跨源"变成"同源"，但它把安全边界搬到了一个**新的、我们目前不控制的服务端进程**上——该进程要转发 Cookie、要自己处理 CORS、要保证不缓存、还要保证不被 SSRF 或路径穿越打穿。当前项目前端只有骨架（Phase 5 才做 UI），先落一个反向代理等于**为了一个尚未存在的客户端引入一层新的信任边界**。方案 A 纯后端可实现、可测试、不新增部署组件，复杂度更低。

**A 方案必须回答的 8 个问题**（详见 §9.3–§9.4）：

| # | 问题 | 结论 | 关键理由 |
|---|---|---|---|
| 1 | 如何生成 | `token = b64u(nonce16) + "." + b64u(ts4) + "." + b64u(HMAC-SHA256(key, "wm-csrf-v1"+nonce+ts)[:16])` | 无状态、可并存多个、不需要存储与轮换表 |
| 2 | 如何与会话绑定 | **`key = sessions.token_hash`**（来自刚校验通过的会话行） | 不同会话必然验不过；不新增配置密钥；泄库也推不出可用令牌 |
| 3 | 未登录的登录/注册怎么保护 | **不发令牌**，靠 `Origin` 严格校验 + `Content-Type: application/json` 强制预检 | 匿名令牌"谁都能领"，攻击者可在自己服务器领一个再塞进表单，起不到防护作用（§9.5 有对照表） |
| 4 | 登录后如何建立新状态 | 登录/注册**响应体直接带新会话的令牌**，前端同时丢弃旧值 | 省一次往返，也消除"先发请求后取令牌"的竞态 |
| 5 | 退出/撤销/过期如何失效 | 令牌**无存储**，失效靠"会话先失效"（401 优先于 403） | 不需要 CSRF 撤销列表；撤销一行 UPDATE 即全场失效 |
| 6 | 如何防跨用户/跨会话复用 | key 由服务端从 Cookie 推导，绝不取请求自报字段 | 见 §9.4 的"四种攻击尝试"表；CSRF 令牌**永远不作为身份** |
| 7 | `Origin` 与令牌的分工 | `Origin` 管"这请求是不是从允许的源发出"；令牌管"发请求的 JS 是否真的在这个会话里" | 两者拦截的攻击面不同，不能互相替代（§9.6 逐接口列出） |
| 8 | 如何避免进日志 | 只走请求头；日志过滤器加 `x-csrf-token`；错误体不回显 | 放 URL 会进访问日志/历史/`Referer` |

**父域 Cookie 为什么不用**：把 `Domain` 设为 `.example.com` 会让令牌对**所有子域可读可写**，等于把 CSRF 防护建立在"所有子域都不失陷"上，而威胁模型（§3.2 T3）恰恰假设子域会失陷。

### 问题 2：Cookie 滑动续期

核心结论（§7.2）：**续期是"一个动作、两个效果"，由同一个布尔量控制。**

- 条件更新 `rowcount == 1` → **才**发 `Set-Cookie`；`rowcount == 0` → **一定不发**。
- 这直接回答"不要把更新 `last_seen_at` 误认为 Cookie 已续期"：只写库不发 Cookie，浏览器会先死（安全方向的 bug）；只发 Cookie 不写库，服务端先死但浏览器还在送（**真空洞**）。两者都不允许。

### 问题 3：开发身份与认证测试矩阵

修正了 v1 的错误结论：**"无 Cookie 必然 401"只在开发身份关闭时成立**。§13.2 给出 11 行矩阵（环境 D/N/T/P × 无 Cookie / 有效 / 无效 / 带令牌），并单列 §13.3 的 7 种 Cookie 状态。关键分支：

| 环境 | 无 Cookie | 无效 Cookie |
|---|---|---|
| D（开发身份开） | **200**（有意为之） | **401**（不回落，防"带坏 Cookie 就静默换身份"） |
| N（开发身份关）/ P | 401 | 401 |

### 问题 4：限流部署假设

- 验收边界写进文档：**本阶段只按单实例、单 worker 验收**（§11.1）。
- 明确多 worker / 多实例下"实际配额 × N"且退避各自独立，**不得声称全局有效**。
- `RateLimiter` 协议 + 时钟注入（§11.2），换 Redis 只改注入的一行。
- 登录/注册限流各有测试用例（§11.4，8 条）。
- Argon2id 增补**并发内存**评估：`memory_cost` 是每哈希，不是总量；用信号量把并发限到 4（≈256 MiB），并说明队列本身是低成本 DoS、必须与限流配合（§8.1）。

### 问题 5：认证接口来源校验

§9.6 给出逐接口矩阵（11 行），并明确三条通用规则：写方法一律要求 `Origin`；带会话 Cookie 的写请求一律要求令牌；`X-Requested-With` / `Referer` / 自定义头**一律不作为防护依据**。另外：

- 登录/注册也要考虑 Login CSRF（新增 U6b）。
- CORS ≠ CSRF 单列一节（§9.7），说明"简单请求"绕过预检的机制。
- 缺失 `Origin` 的浏览器写请求**默认拒绝**，无例外分支。
- 非浏览器客户端**不给头豁免**；将来走独立的 `Authorization: Bearer` 认证面（本轮不做）。

---

## 3. CSRF 完整请求流程

```
① 应用启动（或需要写操作前）
   前端 ── GET /api/v1/auth/csrf ──→ 后端
                                      ├─ 解析会话 Cookie（四判据）
                                      ├─ 无会话 → 401
                                      └─ 有会话 → key=token_hash
                                          生成 (nonce, ts, mac)
        ←── 200 {csrf_token, expires_in}   Cache-Control: no-store, Vary: Origin
   前端：token 存内存（模块变量），不写 storage

② 登录
   POST /auth/login  (Origin 必须合法, Content-Type: application/json)
        ←── 200 {user, csrf_token}  + Set-Cookie: wm_session=...; HttpOnly; SameSite=Lax; Max-Age=604800
   前端：丢弃匿名阶段的任何旧 token，改用响应里的新 token
   （登录请求本身不带 token —— §9.5）

③ 写请求
   POST /api/v1/items
     Header: X-CSRF-Token: <token>
             Origin: https://www.example.com
             Content-Type: application/json
   后端顺序（不可调换）：
     1) Origin 校验        失败 → 403 origin_not_allowed
     2) 会话解析（SQL 四判据）失败 → 401 authentication_required + 清 Cookie
     3) 令牌校验            失败 → 403 csrf_token_missing / _invalid / _expired
     4) 节流续期（条件 UPDATE，rowcount=1 才 Set-Cookie）
     5) 构造 UserContext(session_id=...) → 仓储 WHERE user_id=?

④ 令牌过期（>12h）
   403 csrf_token_expired → 前端重取一次（回到 ①）并重试一次原请求
   仍失败 → 提示用户，禁止无限重试

⑤ 退出
   POST /auth/logout  (Origin + 有会话时带 token)
     → revoked_at=now(), reason='logout'
     → 204 + Set-Cookie: wm_session=; Max-Age=0
   前端：清空内存 token
   此后该 token 即使被保存也无效（会话已 401，走不到令牌校验）

⑥ 改密
   POST /auth/password (Origin + token + 当前密码)
     → 撤销该用户其它全部会话（reason='password_change'）
     → 当前会话保留且不换令牌（不引入并发互踢）
```

**为什么第 3 步必须在第 2 步之后**：令牌的 key 来自"校验通过的会话行"。颠倒顺序就只能用一个与身份无关的 key，那等于退回随机串比对。

---

## 4. Cookie 滑动续期的具体规则

| 项 | 规则 |
|---|---|
| 空闲窗口 | 7 天，判据 `now() - last_seen_at < 7d` |
| 绝对上限 | 30 天，判据 `absolute_expires_at > now()`，签发时写死 |
| `last_seen_at` 更新条件 | `UPDATE ... WHERE id=:sid AND revoked_at IS NULL AND absolute_expires_at > now() AND last_seen_at < now() - interval '5 minutes'` |
| 写入方式 | 条件 UPDATE，**不读-改-写**、不加锁；并发下最多一个 `rowcount=1` |
| 何时重发 `Set-Cookie` | **仅** `rowcount==1` 时；另加 login/register 签发、401 清除、logout 清除 |
| `Max-Age` | `min(7d, absolute_expires_at - now)`；正常 604800，接近绝对上限时缩短 |
| 绝对过期检查 | 每次都用 SQL 比时间，**不依赖浏览器本地过期**（客户端时钟不可信） |
| 过期收尾 | best-effort 写 `revoked_at` + `revoked_reason=idle_expired/absolute_expired`；写失败不影响返回 401 |
| 已失效请求 | 401 + `Set-Cookie: wm_session=; Max-Age=0` |
| 哪些请求不续期 | `/health`、401 请求、**CSRF 校验失败（403）的请求** |
| 令牌轮换 | 不做。续期只动时间，不动令牌 |

**与"误认为 Cookie 已续期"直接相关的三条禁令**：① 不许"写库了就当 Cookie 也新了"；② 不许"发 Cookie 了就当库也更新了"；③ 不许在任何一侧单独前移时间。

---

## 5. 修订后的认证与开发身份测试矩阵（摘要）

| # | 环境 | 携带 | `/items` 期望 | `auth_mode` |
|---|---|---|---|---|
| 1 | D | 无 Cookie | **200** | `development_identity` |
| 2 | D | 有效会话 | 200 | `session` |
| 3 | D | 无效 Cookie | **401**（不回落） | `unauthenticated` |
| 4 | D | 有效会话、写请求缺 token | 403 | `session` |
| 5 | N | 无 Cookie | 401 | `unauthenticated` |
| 6 | N | 有效会话 | 200 | `session` |
| 7 | T（pytest 默认） | 任意 | 等价 N；开发身份需显式 fixture | — |
| 8 | P + `DEV_USER_ENABLED=true` | 任意 | **进程启动失败** | — |
| 9 | P | 无 Cookie | 401 | `unauthenticated` |
| 10 | P | 无效/过期/撤销 Cookie | 401 | `unauthenticated` |
| 11 | P | 任意"开发身份"自定义头/参数 | 401（不读取） | — |

Cookie 状态 7 细分（缺失/格式非法/未知哈希/空闲过期/绝对过期/退出撤销/改密撤销）全部 401；响应体一致，成因只进日志。

CSRF 14 条、续期 8 条、限流 8 条用例见 §16.2 / §16.3 / §11.4。

---

## 6. 仍然存在的风险与未解决问题

### 6.1 知情接受（不会在 Phase 3 消除）

| # | 风险 | 影响 | 为什么接受 |
|---|---|---|---|
| R1 | 注册接口可枚举邮箱（`409 email_taken`） | 泄露"某邮箱注册过" | 无邮件通道时"假 202"是骗人；用 5 次/小时/IP 限流压制（D3） |
| R2 | 无邮箱验证 | 抢注他人邮箱、打错字即失联 | 需邮件通道；已在界面文案层面写明"忘密码即永久丢失" |
| R3 | 无找回密码 | 账号可能永久丢失 | 同上，且这是**与认证同等优先**的后续项 |
| R4 | XSS 可代用户发请求（含读内存 token） | 会话被滥用 | `HttpOnly` 已阻断"外带令牌"；CSP 属 Phase 6 |
| R5 | 撤销不能中断在途请求 | 最多一个请求时长的窗口 | 无分布式取消机制，成本远超收益 |
| R6 | 进程内限流在多 worker 下失效 | 配额 × N | 已把"单实例单 worker"写成验收边界 |
| R7 | 按 IP 限流在 NAT 下误伤 | 共享出口的用户互相影响 | 换账号维度退避已覆盖主要场景；不做 IP 封禁 |

### 6.2 需要部署与运维配合（否则防线会静默失效）

| # | 风险 | 触发条件 | 缓解 |
|---|---|---|---|
| R8 | `Origin` 白名单配错（漏配/通配） | 上线配置失误 | 白名单**精确匹配**、不允许正则/通配；上线检查清单列入 runbook 计划 |
| R9 | 反向代理缓存 `no-store` 响应 | 中间层忽略缓存头 | 部署时显式关闭认证路径缓存；runbook 检查项 |
| R10 | 服务器时钟漂移 | NTP 未配 | 时间判据全用 `now()`（数据库时钟）；上线要求 NTP；漂移会导致"批量过期"而非"永不过期"（方向安全） |
| R11 | 访问日志记录响应体 | 开了 body logging | runbook 明令禁止；`redact()` 覆盖响应侧 |

### 6.3 设计上仍需你确认的口径

| # | 问题 | 我的建议 |
|---|---|---|
| Q1 | Phase 3 是否**只按单实例、单 worker 验收** | 是。若半年内要上多 worker，现在就该把限流换 Redis，否则会被迫返工 |
| Q2 | CSRF 令牌 TTL 12 小时是否合适 | 合适。更短会更频繁触发"403 → 重取"，更长会扩大被复用的时间窗 |
| Q3 | 是否接受"登录/注册不要求 CSRF 令牌" | 接受。这是本轮的**核心论证之一**（§9.5），不是省事 |
| Q4 | `purge_expired` 何时落地 | 可以先只留函数不接定时任务；会话表在几十人规模下增长可忽略 |
| Q5 | 路线图是否需要同步 | 见 §6.4 |

### 6.4 关于 `docs/planning/WearMind-Project-Roadmap.md`

**文件存在，但本轮没有修改**（按要求先提议）。它有两处已被本轮决策"超车"：

| 位置 | 现状 | 建议改法 |
|---|---|---|
| 第 295–297 行 | 把"单用户还是多用户""会话 Cookie / JWT / OAuth""部署域名与跨域策略"列为待定 | 标注"已于 2026-10-25 由 D1/D2/D7 决定：多用户开放注册、服务端会话 Cookie、暂不部署生产" |
| 第 783–784 行 | 勾选项"用户登录范围""正式认证方式"仍未勾 | 勾选并附一句指向 `phase3-auth-design.md` §18 |

> 这两处不同步不会导致实现错误（设计文档已是权威），但会让"路线图说还没定、设计说已定"长期并存。**是否要改，等你一句话。**

---

## 7. 修改文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `docs/design/phase3-auth-design.md` | 修改（v1 → v2） | 552 → 1099 行；+697 / −118 |
| `docs/planning/phase3-auth-design-review.md` | **新建** | 本报告 |
| `docs/runbooks/auth-cookie-policy.md` | **未创建** | 仅列出计划内容（设计文档 §19.1） |
| `docs/planning/WearMind-Project-Roadmap.md` | **未修改** | 见 §6.4 |

除此之外没有任何文件被读写（审计报告 `docs/reports/2026-10-25-phase2.8-independent-audit.md` 是复审前就已存在的未跟踪文件，本轮未动）。

---

## 8. 确认没有修改代码 / 依赖 / 数据库 / 环境变量 / Git 历史

| 约束 | 状态 | 依据 |
|---|---|---|
| 不修改应用代码 | ✅ 未改 | `git status` 只有 1 个 modified（文档） |
| 不安装/升级依赖 | ✅ 未改 | 未执行任何包管理命令；`pyproject.toml` / `uv.lock` 无变化 |
| 不创建数据库迁移 | ✅ 未改 | `alembic/versions/` 无新文件；未执行任何 alembic 命令 |
| 不修改数据库 | ✅ 未改 | 未连接数据库、未执行 SQL |
| 不修改 `.env` / 系统配置 | ✅ 未改 | 未读写任何 `.env`；未改环境变量 |
| 不创建 Git 提交 | ✅ 未提交 | `git log` 顶端仍是 `fa6d1d3` |
| 不推送远程 | ✅ 未推送 | `ahead 4 / behind 0` 与复审前一致 |
| 不开始 T1–T10 | ✅ 未开始 | 无任何代码文件变动 |
| 不打印密钥/密码 | ✅ 未触碰 | 本轮未读取 `.env`，未连接数据库 |

---

## 9. Git 状态与 diff 摘要

```
$ git status --short
 M docs/design/phase3-auth-design.md
?? docs/reports/2026-10-25-phase2.8-independent-audit.md   ← 复审前已存在，未动

$ git diff --stat
 docs/design/phase3-auth-design.md | 815 ++++++++++++++++++++++++------
 1 file changed, 697 insertions(+), 118 deletions(-)

$ git log --oneline -1
 fa6d1d3 docs: add phase 3 authentication design and threat model
```

（本报告的 `docs/planning/phase3-auth-design-review.md` 是在 `git status` 之后创建的新文件，属于本轮产出的第二个未跟踪文件。）

`git diff --check` 通过：无尾随空白、无冲突标记。

---

## 10. 建议：是否可以开始 T1

**建议：可以，但先满足两个前置条件。**

| 前置条件 | 为什么必须先做 |
|---|---|
| ① 先推送现有 4 个提交（`5d6bdd0` / `e90b8f6` / `91db427` / `fa6d1d3`） | 否则认证代码的提交会和这批文档混在同一次推送里，review 时无法分离"文档变更"与"行为变更" |
| ② 确认 Q1：Phase 3 按"单实例、单 worker"验收 | 这决定 T6 的实现深度。若要支持多 worker，限流必须从一开始就走外部存储，否则 T6/T10 要重写 |

**T1 的第一件事不是写代码，是测量**：在目标机器上量出 Argon2id 的**单次中位耗时**与**并发峰值 RSS**，用实测值定 `time_cost` / `memory_cost` / `AUTH_HASH_CONCURRENCY`。v1 只要求测耗时，v2 补上并发内存 —— 那才是能把服务打崩的一面。

**不建议现在就做的事**：不要为了"看起来完整"提前引入 Redis、邮件通道、CAPTCHA 或 CSP。它们各自解决的是本阶段明确排除的问题（§19），提前做会稀释 Phase 3 的可验收性。
