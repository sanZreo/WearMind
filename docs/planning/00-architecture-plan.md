# WearMind 技术调研与架构规划 v0.1

> 阶段：Phase 0 前置调研（仅检查与规划，未编写业务代码）
> 生成时间：2026-10-25
> 工作目录：`E:/WearMind`

## 阅读指南：证据分级

本文所有结论都标注了来源等级，请勿混用：

| 标记 | 含义 |
|---|---|
| ✅ **实测** | 我在本机实际执行命令并读到了输出，可直接采信 |
| 🔶 **推断** | 基于实测数据 + 技术经验的判断，方向可信，但具体数值/行为需验证 |
| ❓ **待确认** | 我无法验证（权限、沙箱限制、需要你的账号或决策），必须由你回答 |

**本次未做的事**：没有安装任何依赖，没有修改系统设置，没有下载模型，没有初始化 git，没有覆盖任何文件。除本文档外未创建任何项目文件。

---

# A. 环境检查报告

## A.1 操作系统与硬件（✅ 实测）

| 项目 | 实测值 | 评价 |
|---|---|---|
| 操作系统 | Windows 11 家庭版，`10.0.26200` | 满足要求（25H2 分支） |
| 架构 | 64 位 | 正常 |
| CPU | AMD Ryzen 7 8845H（8 核 16 线程） | 够用 |
| 内存 | 总计 **15.3 GB**，当前空闲 **4.1 GB** | ⚠️ **本机最大瓶颈**，见 E-01 |
| C 盘 | 已用 311.8 GB / 剩余 **87.4 GB** | 可放系统与工具 |
| D 盘 | 剩余 223.8 GB | 可放模型/数据 |
| E 盘 | 剩余 **374 GB** | 项目所在盘，空间充足 |

## A.2 开发工具链（✅ 实测）

| 工具 | 状态 | 详情 |
|---|---|---|
| Python | ✅ | `3.13.14`（系统）；另有托管版 `3.13.12` |
| pip | ✅ | `26.1.2` |
| uv | ✅ | `0.12.9`（x86_64-pc-windows-msvc）→ **建议作为 Python 依赖管理主力** |
| Node.js | ✅ | `v22.22.2`（LTS 线） |
| npm / npx | ✅ | `10.9.7` / `10.9.7` |
| pnpm / yarn | ❌ 未安装 | 非阻塞，npm 可用 |
| Git | ✅ | `2.55.0.windows.3` |
| Docker CLI | ⚠️ 半可用 | 客户端 `29.7.2` 已装，但 **daemon 未运行**（`dockerDesktopLinuxEngine` 管道不存在） |
| Ollama | ⚠️ 半可用 | 客户端 `0.33.3` 已装，**服务未运行**（`could not connect to a running Ollama instance`） |
| PostgreSQL | ❌ **未安装** | 无 `psql` 命令，无 `postgres*` Windows 服务，5432 端口空闲 |
| VS Code | ❓ **未找到** | 标准安装路径（用户级 / 系统级）均不存在，`code` 不在 PATH |

## A.3 关键服务与端口（✅ 实测）

| 端口 | 用途 | 状态 |
|---|---|---|
| 3000 | Next.js | 空闲 |
| 8000 | FastAPI | 空闲 |
| 5432 | PostgreSQL | 空闲（无服务占用） |
| 11434 | Ollama | 空闲 |

结论：端口无冲突，可按下述默认分配直接使用。

## A.4 网络与包源（✅ 实测）

| 项目 | 结果 |
|---|---|
| PyPI 连通性 | HTTP `200` |
| npm registry | HTTP `200`，当前源为官方 `https://registry.npmjs.org/` |
| 代理环境变量 | `HTTP(S)_PROXY = http://127.0.0.1:13728`（工具内置代理，非系统全局代理） |

🔶 推断：官方源可用但国内直连速度可能不稳，安装阶段若出现超时，切换 npmmirror / 清华 PyPI 镜像即可，不影响架构。

## A.5 本地模型资产（✅ 实测 —— 重要发现）

```
~/.ollama/models/blobs          6.2 GB
已下载模型清单：qwen3.5:9b
  ├─ layer: application/vnd.ollama.image.model      6.59 GB
  ├─ layer: application/vnd.ollama.image.license
  └─ layer: application/vnd.ollama.image.params
```

**关键判断（🔶 强推断，基于 manifest 结构）**：
该模型 manifest 中 **不存在 `application/vnd.ollama.image.projector` 层**，而视觉模型（VL）必须有投影层才能接收图像输入。
→ **`qwen3.5:9b` 是纯文本模型，无法识别衣物照片。**

这直接影响架构：**本地 Ollama 路线在第一版没法承担"看图"任务**，必须做能力降级设计（详见 B.7 Q6）。

## A.6 Git 配置（✅ 实测）

```
git config --global --list
  → safe.directory=*
```

**`user.name` 与 `user.email` 均为空。** 提交前必须配置，否则 `git commit` 会失败或写入错误身份。

## A.7 目录状态（✅ 实测）

`E:/WearMind` 初始为**完全空目录**（无文件、无隐藏文件、无 `.git`、无 `.workbuddy`）。
→ **不存在既有重要项目，可安全创建文件。** 本报告仅新建了 `docs/planning/`。

## A.8 可复用的 Skill / 开发能力（✅ 实测清单）

与本项目相关的可用能力（已验证存在，非虚构）：

| 能力 | 名称 | 对本项目的价值 |
|---|---|---|
| 云托管后端 | `cloud-service` | 可选：替代自建 PG 的托管数据库/认证/存储，可用于快速验证 |
| 发布上线 | `发布为应用` （sites） | Phase 5 把 Web 应用发布成可访问链接 |
| PPT / Word / Excel | `workbuddy-pptx` / `workbuddy-docx` / `workbuddy-sheet-*` | 产出架构评审稿、测试用例表、数据字典 |
| PDF 处理 | `pdf` / `pdfkit-py` | 需求文档、发票/收据类输入解析 |
| 浏览器自动化 | `playwright-cli` / `browser-use` | Phase 5 E2E 测试、页面截图回归 |
| 图片处理 | `buddy-image-processing` | 去水印、抠图（衣物白底图）、增强 —— 对衣柜图片规范化有直接价值 |
| 资料库 | `library` | 把规划文档、知识沉淀到云端工作台 |
| 批量安全改码 | `safe-batch-code-patch` | 跨多文件重构时避免破坏性改动 |
| 提交打包审查 | `review-submission-packaging` | 阶段交付物打包与自审 |
| 专家能力 | `workbuddy-finance-skill` 等 | 本项目暂不需要 |

**如实说明**：以上是通用能力，**没有**"专为 FastAPI/Next.js 开发"的专用脚手架 Skill。前后端代码仍需按标准工程实践构建。

## A.9 环境结论

| 等级 | 项目 |
|---|---|
| 🟢 可直接用 | Node/npm、Python/uv、Git、端口、磁盘、网络、云托管与发布能力 |
| 🟡 需先启动/配置 | Ollama 服务、Docker Desktop 引擎、Git 身份、VS Code（若确实要用） |
| 🔴 **必须你决策或安装** | **数据库（PostgreSQL 未装）**、**视觉模型缺失**、**内存余量紧张** |

**这三个红色项如果不解决，Phase 1 无法开始。**

---

# B. 推荐技术架构

## B.1 总体形态：前后端分离 + 单一后端权威数据源

```
┌─────────────────────────────────────────────────────────────┐
│  浏览器                                                        │
│  Next.js 16 (App Router, RSC)  —— 只做 UI + BFF 转发          │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS / JSON（OpenAPI 契约）
┌──────────────────────────▼──────────────────────────────────┐
│  FastAPI  (apps/api)  —— 唯一业务权威                          │
│                                                              │
│  api/v1  →  domain services  →  repositories  →  PostgreSQL  │
│                 │                                            │
│                 ├── agents/   LangGraph 状态机 + 工具 + 校验器  │
│                 ├── llm/      统一模型适配层（唯一出口）        │
│                 ├── vision/   图片解析流水线                    │
│                 └── storage/  本地文件抽象（可换 S3）           │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼───────────────────┐
        ▼                  ▼                   ▼
   PostgreSQL        LLM Providers        APScheduler
   (单一库)      在线 API / Ollama        独立 worker 进程
```

### 硬性架构规则（不可妥协的三条）

1. **Next.js 不直连数据库。** 所有数据读写经 FastAPI。避免两套 schema 认知、避免绕过校验层改数据。
2. **业务代码不 import 任何厂商 SDK。** 只有 `llm/providers/*` 允许出现 `openai` / `ollama`。业务层只依赖 `LLMProvider` 协议。
3. **推荐结果里的衣物来自数据库，不来自模型文本。** 模型只允许输出 `item_id`，展示内容由后端按 id 回查渲染（见 B.7 Q2）。

## B.2 关于"是否机械使用每一项技术"的结论

基于实测环境，我的取舍如下（详细理由见 H 章）：

| 技术 | 结论 | 说明 |
|---|---|---|
| Next.js + TypeScript | ✅ **保留** | Next `16.4.3` / React `19.3.1` |
| FastAPI + Python | ✅ **保留** | FastAPI `0.162.0`，Python 3.13 兼容良好 |
| PostgreSQL | ✅ **保留（但改安装方式）** | 本机未装；**建议原生安装，不要依赖 Docker**（见 E-02） |
| SQLAlchemy | ✅ **保留，但用同步模式** | `2.1.6`。异步在本项目收益低、调试成本高 |
| Alembic | ✅ **保留** | `1.20.1`，schema 演进的唯一手段 |
| LangGraph | 🟡 **保留但严格限缩** | `1.2.17`（已 GA）。只用一个线性 StateGraph，不用多智能体 |
| Ollama | ✅ **保留为可选执行器** | 已装，但缺视觉模型；只承担文本任务 |
| APScheduler | 🟡 **保留，但从 FastAPI 里挪出去** | `3.11.3`。放独立 worker，否则多进程会重复触发 |
| Pytest | ✅ **保留，且提前投入** | 校验器、隔离性、幂等性全靠它守 |

## B.3 数据模型草案（PostgreSQL）

核心表（字段略，只表达关系）：

```
users ──┬── user_profiles        身高/体型/尺码/风格倾向
        ├── items ──── item_images        衣物主表 / 多图
        │      └──── item_attributes      颜色/品类/材质/季节/场景标签
        ├── outfits ─── outfit_items      一次完整穿搭（引 items）
        ├── suggestions                   每日建议（对 outfits 的封装）
        ├── feedback                      喜欢/不喜欢/穿了/没穿 + 原因
        ├── preferences                   偏好（⭐ 带 source 区分明确/推断）
        ├── conversations ── messages     对话与工具调用轨迹
        ├── agent_runs ──── tool_calls    每次 Agent 执行的可观测记录
        └── job_runs                      定时任务幂等记录
```

**两个必须先设计对的字段**（后期改代价极大）：

- `preferences.source`：`explicit | inferred | system_default` + `confidence` + `evidence jsonb` + `expires_at`
- `suggestions`：`UNIQUE(user_id, target_date, kind)` —— 这是定时任务幂等的地基

## B.4 模型接入层（统一适配层的具体形态）

```python
# llm/base.py  —— 业务层唯一可见的契约
class ModelCapability(StrEnum):
    TEXT = "text"; VISION = "vision"
    TOOL_CALLING = "tool_calling"; JSON_SCHEMA = "json_schema"
    STREAMING = "streaming"

@dataclass(frozen=True)
class ModelProfile:
    alias: str                  # "cloud-fast" / "local-9b"
    provider: str               # "openai" | "ollama"
    capabilities: frozenset[ModelCapability]
    context_window: int
    cost_tier: int              # 0=免费本地, 1..n=越贵越大
    privacy_tier: str           # "local" | "external"

class LLMProvider(Protocol):
    async def chat(self, req: ChatRequest) -> ChatResponse: ...
    async def stream(self, req: ChatRequest) -> AsyncIterator[Chunk]: ...
    async def health(self) -> ProviderHealth: ...
```

三层路由，互不耦合：

```
业务代码  →  ModelRouter.route(role="recommend", requires={TOOL_CALLING})
                    │
                    ├─ 1. 候选筛选：按 capabilities 过滤（硬约束）
                    ├─ 2. 策略排序：按 用户设置 → 全局默认 → 成本/隐私策略
                    └─ 3. 降级链：primary 失败 → fallback（带熔断器）
                    │
                    ▼
            Provider 注册表  →  openai.py / ollama.py / (未来任意)
```

**关键点**：`role`（用途）与具体模型解耦。配置文件里只写"推荐任务用 `recommend` 角色"，改模型 = 改一行配置，不动代码。

## B.5 图片处理流水线（隐私优先）

```
上传 → ① 校验(类型/尺寸/大小) → ② 剥离 EXIF（含 GPS）→ ③ 等比压缩至 ≤1600px
     → ④ 生成缩略图 + 感知哈希（去重）
     → ⑤ [可选] 抠主体/人脸模糊（OCR 前处理）
     → ⑥ 按 PRIVACY_MODE 决定：仅本地解析 / 可外发解析
     → ⑦ 产出 draft item（草稿）→ 用户确认 → 正式入库
```

存储路径 `var/uploads/{user_id}/{uuid}.{ext}`，**不做静态目录暴露**，只允许经鉴权接口读取（防越权遍历）。

## B.6 Agent 设计（LangGraph 限缩版）

```python
StateGraph(RecommendState)
  load_context      # 用户画像 + 偏好 + 天气 + 历史反馈（纯代码，非 LLM）
      ↓
  retrieve_wardrobe # 工具调用：按场景/季节/温度筛候选衣物（确定性 SQL）
      ↓
  plan              # LLM：在候选集内组合方案（structured output）
      ↓
  validate          # ⭐ 确定性校验器：item_id 必须 ∈ 本次候选集，且属于该用户
      ↓ (不通过)
  repair  ──────────┘   （最多 N 次，超过则降级为规则推荐）
      ↓ (通过)
  persist           # 落库 + 生成 agent_run 轨迹
```

**为什么这样设计**：LLM 只做"从给定集合里挑与排序"，不做"凭空生成衣物"。所有事实性内容由代码保证。这让"推荐不存在的衣物"从概率问题变成结构上不可能。

## B.7 八个架构难题的具体方案

### Q1 如何隔离不同用户的数据？

四层纵深防线，**不依赖任何单一机制**：

1. **Schema 层**：所有业务表强制带 `user_id`（`NOT NULL` + 外键 + 索引），无例外。`items` 等表加 `UNIQUE(user_id, id)` 便于复合外键。
2. **访问层**：Repository 方法的签名**必须**接收 `UserContext`，且 `user_id` 从 `UserContext` 取而非从参数传入 —— 从接口设计上让"忘记加 user_id 过滤"变得难以发生：

   ```python
   class ItemRepository:
       def __init__(self, session: Session, ctx: UserContext): ...
       def get(self, item_id: UUID) -> Item:   # 内部固定 .where(Item.user_id == self.ctx.user_id)
   ```
3. **测试层**：一组"越权测试"——用户 B 的 token 访问用户 A 的每个资源，必须全部返回 404（不是 403，避免存在性泄露）。
4. **存储层**：文件路径含 `user_id`，下载走签名/鉴权端点；Provider 外发时按用户隔离配额与审计。

🟡 **可选加分项（Phase 6 再做）**：PostgreSQL Row Level Security，配合 `SET LOCAL app.current_user_id`。它能在数据库层兜底，但会给连接池与调试带来额外复杂度，**不建议第一版就上**。

### Q2 如何确保 Agent 只推荐真实存在于用户衣柜中的衣物？

**核心原则：LLM 做"选择"，代码做"事实"。** 三层拦截：

1. **输入约束**：模型只能看到本次 `retrieve_wardrobe` 返回的候选集（带 `item_id`），prompt 明确"只能使用下列 id"。
2. **输出约束**：structured output 用 JSON Schema 强制 `item_id` 为 UUID 格式，禁止自由文本衣物名。
3. **后置校验（决定性）**：
   ```
   对每个推荐方案的每个 item_id：
     if id ∉ candidate_set:  → 该条推荐判定非法（不是"提示模型重试"而是直接拒绝）
   ```
   校验器是**纯 Python、无 LLM 参与**的。加上数据库侧 `WHERE user_id = :ctx_user AND id = ANY(:ids)` 复核，双保险。
4. **渲染约束**：前端展示的图片/名称/颜色全部由后端按 id 回查 DB，**不采信模型输出的任何描述性文字**（模型可以说"这件藏青针织衫很适合"，但显示的名字取自 DB 字段）。

效果：即使模型产生幻觉，用户界面也不可能出现衣柜里没有的衣服。

### Q3 如何区分用户明确表达的偏好和模型推断的偏好？

`preferences` 表设计 + 写入纪律 + 注入纪律：

| 维度 | explicit（明确） | inferred（推断） |
|---|---|---|
| 产生方式 | 用户在设置页填写 / 对话中明确说"我不穿高跟鞋" | 独立的记忆抽取步骤，从历史对话与反馈中归纳 |
| 写入权限 | 只有用户操作或用户原话的确定性解析 | 只有 `memory_extractor` 服务可写 |
| `confidence` | 恒为 `1.0` | 0.3–0.9，需 ≥N 次证据才允许写入 |
| 冲突处理 | **绝对优先**，可覆盖/删除 inferred | 与 explicit 冲突时自动失效 |
| 时效 | 长期，除非用户修改 | 带 `expires_at`，需定期复核 |
| UI 呈现 | 设置页"我的要求" | 单独区块"我猜你可能喜欢"，可一键确认→升级为 explicit |

**Prompt 注入纪律**：两类偏好必须放在**不同标签块**里，并写明冲突时的裁决规则：

```
<explicit_preferences>  用户明确表达，必须遵守，不可违背
<inferred_preferences>  模型推断，仅作参考；与上面冲突时一律忽略
```

**禁止**把两者混成一个 `preferences` 列表塞给模型——这是这类系统最常见的隐蔽 bug 来源。

### Q4 如何避免定时任务重复执行？

**四重保障，任一层失效都不至于产生重复建议：**

1. **进程隔离**：调度器运行在独立 `worker` 进程（`python -m app.workers`），**不放在 FastAPI 里**。FastAPI 用 `--workers N` 时进程内调度器会触发 N 次。
2. **数据库唯一约束（真正的守卫）**：`suggestions` 上 `UNIQUE(user_id, target_date, kind)`。
3. **原子领取（claim）模式**：
   ```sql
   INSERT INTO job_runs (job_key, user_id, target_date, status)
   VALUES (...) ON CONFLICT (job_key) DO NOTHING RETURNING id;
   -- 返回空 = 已被别的执行者领取 → 本次直接跳过
   ```
   注意：**先 claim 再干活**，不是干完再记录。
4. **分布式锁**：长任务用 `pg_try_advisory_lock(hashtext('daily_suggestion'))`，进程崩溃时锁自动释放。

配套：`job_runs` 记录 `status / attempt / started_at / error`，失败可重试且重试安全。

### Q5 如何在在线模型和 Ollama 之间切换？

- **切换粒度**：全局默认 / 单用户设置 / 单任务角色覆盖（三级，后者优先）。
- **切换方式**：改配置或调 `/api/v1/settings/model`，**不重启、不改代码**。`ModelRouter` 每次调用时读取当前配置（带短 TTL 缓存）。
- **一致性风险**：不同模型的能力、JSON 遵循度、中文表达差异很大。因此：
  - 所有面向模型的请求-响应都用**结构化 schema**，而不是自由文本解析；
  - 关键 prompt 有一组**回归测试用例**（固定输入 → 断言输出结构合法），切换模型前后各跑一遍；
  - UI 上标注"当前由本地模型生成"，让用户预期合理。
- **健康检查**：`ollama.health()` 探测 11434 端点与模型是否已拉取；不可用则自动回退在线模型并在响应里标注 `degraded: true`。

### Q6 如何处理模型不支持视觉或工具调用？

这是**本机必然会遇到**的情况（已实测：本地仅 `qwen3.5:9b`，无视觉能力）。方案是"能力声明 + 按需路由 + 显式降级"：

**能力路由**：任务声明所需能力，Router 只选满足全部硬约束的模型。选不到就进入降级，而不是报错或强行调用。

| 缺失能力 | 降级策略 |
|---|---|
| **无视觉** | ① 路由到有视觉能力的在线模型（若 `PRIVACY_MODE` 允许）；② 若不允许外发 → 本地兜底：PIL 提取主色板 + 轻量分类模型（品类/图案）产出**草稿标签**，UI 提示"这是本地粗识别，请确认/修正"；③ 最差：引导用户文字描述（"黑色羊毛大衣"） |
| **无工具调用** | 切换为**文本 ReAct 模式**：让模型输出 `{"action": "search_wardrobe", "args": {...}}` 的 JSON，运行时解析→执行→把结果作为下一轮输入回灌。对模型能力要求更低，代价是轮次多、延迟高。此模式作为独立的 `ToolStrategy` 实现，与原生 function calling 共用同一套工具定义 |
| **无 JSON schema 支持** | 同上，用"约束解码 + 正则修复 + 二次校验"，失败则重试有限次后降级为规则推荐 |
| **上下文窗口小** | 候选集分页检索 + 摘要压缩，绝不把整柜衣物塞进 prompt |

**关键设计**：能力缺口在**配置层显式声明**（`ModelProfile.capabilities`），而不是靠运行时 try/except 猜。这样"某个模型能不能看图"是部署时的已知事实。

### Q7 如何避免把用户图片和个人信息发送给不必要的外部服务？

**原则：默认最小外发，外发需可解释、可审计、可关闭。**

1. **三级隐私模式**（`PRIVACY_MODE`）：
   - `local_only`：图片永不出本机。视觉任务只能本地处理或走文字降级。
   - `hybrid`（默认建议）：**只外发裁剪后的单品区域图**（不含人脸、不含全身、不含背景），文字侧只发结构化标签。
   - `cloud_ok`：允许外发原图，用于效果最佳场景，需用户逐次或一次性授权。
2. **上传即脱敏**：剥离 EXIF（GPS/设备/时间）、可选人脸检测打码、可选背景移除，只留衣物主体。
3. **按用户隔离的授权状态**：`user_privacy_settings` 记录是否允许外发、允许哪些服务商。
4. **外发审计表** `external_calls`：记录 `provider / purpose / 数据类型 / payload_hash / 时间 / user_id`。**记录哈希而非内容**，既能审计又不二次留存。
5. **可替代性**：天气用 **Open-Meteo**（免费、无需 API Key、不追踪用户）替代需要实名 Key 的商业天气 API。
6. **绝不**把用户画像、衣柜全量、历史反馈打包发给模型 —— 只发送当前任务必需的最小子集。

### Q8 如何保证模型调用失败时业务系统能正确处理？

**分层隔离：LLM 只在 Agent 层，衣柜 CRUD 完全不依赖 LLM。**

1. **类型化错误**：`LLMTimeout / LLMRateLimit / LLMAuthError / LLMInvalidResponse / LLMContentFiltered / ProviderUnavailable`，每种映射到明确的重试策略。
2. **重试**：仅对瞬时错误（超时/限流/5xx）做指数退避 + 抖动，上限 3 次；**绝不对 4xx 鉴权错误重试**。
3. **熔断器**：按 provider 统计连续失败，打开后快速失败并走 fallback 链，半开探测恢复。
4. **全程留痕**：每次 Agent 执行写 `agent_runs`（`status / model / tokens / latency / error / step_trace`）。**失败也可复现、可回放**，这是后续调优的唯一依据。
5. **API 契约**：模型失败返回 `503` + `{"error_code": "model_unavailable", "retry_after": 30, "degraded_result": {...}}`。前端据此展示"已用基础规则给出建议"而非白屏。
6. **规则兜底**：温度区间 + 场景 + 衣柜分类做纯 SQL/规则推荐。效果不如 LLM，但**永远有输出**。
7. **超时预算**：单次 Agent 总预算（如 20s）与单步预算（如 8s）分离，防止一次卡死拖垮请求。

---

# C. 项目目录结构

```
E:/WearMind/
├── README.md
├── .gitignore
├── .env.example                    # 唯一配置模板，真实 .env 不入库
├── docker-compose.yml              # 可选：仅用于 PG（若 Docker 可用）
├── docs/
│   ├── planning/00-architecture-plan.md   ← 本文
│   ├── adr/                        # 架构决策记录（每个重要取舍一篇）
│   └── api/                        # 导出的 OpenAPI 契约
│
├── apps/
│   ├── api/                        # ── FastAPI 后端 ──
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── alembic/versions/
│   │   ├── app/
│   │   │   ├── main.py             # 应用装配
│   │   │   ├── core/
│   │   │   │   ├── config.py       # pydantic-settings
│   │   │   │   ├── security.py     # 密码哈希、JWT、Cookie
│   │   │   │   ├── errors.py       # 统一异常 + 错误码
│   │   │   │   ├── logging.py      # 结构化日志 + 请求 ID
│   │   │   │   └── privacy.py      # 隐私模式与授权判定
│   │   │   ├── db/
│   │   │   │   ├── session.py
│   │   │   │   ├── base.py
│   │   │   │   ├── models/         # users.py items.py outfits.py ...
│   │   │   │   └── repositories/   # 全部强制 UserContext
│   │   │   ├── api/v1/
│   │   │   │   ├── deps.py         # 依赖注入：ctx, session, provider
│   │   │   │   └── routers/
│   │   │   │       ├── auth.py  wardrobe.py  uploads.py
│   │   │   │       ├── recommendations.py  feedback.py
│   │   │   │       ├── preferences.py  settings.py  jobs.py
│   │   │   ├── domain/
│   │   │   │   ├── schemas/        # Pydantic DTO
│   │   │   │   └── services/       # 业务编排（不碰 LLM）
│   │   │   ├── llm/
│   │   │   │   ├── base.py         # Protocol + Capability + 错误类型
│   │   │   │   ├── router.py       # 能力路由 + 降级链 + 熔断
│   │   │   │   ├── registry.py     # 模型档案注册表
│   │   │   │   └── providers/
│   │   │   │       ├── openai_compat.py
│   │   │   │       └── ollama.py
│   │   │   ├── vision/
│   │   │   │   ├── pipeline.py     # 校验/EXIF/压缩/缩略图/哈希
│   │   │   │   ├── extractor.py    # 视觉解析 → draft item
│   │   │   │   └── fallback.py     # 无视觉模型时的色彩/品类兜底
│   │   │   ├── agents/
│   │   │   │   ├── graph.py        # LangGraph StateGraph
│   │   │   │   ├── state.py
│   │   │   │   ├── prompts/
│   │   │   │   ├── tools/          # 工具定义（search_wardrobe 等）
│   │   │   │   ├── validators/     # ⭐ item_id 白名单校验
│   │   │   │   └── memory/         # 偏好抽取、历史摘要
│   │   │   ├── storage/
│   │   │   │   ├── base.py         # Storage Protocol
│   │   │   │   └── local.py
│   │   │   ├── integrations/
│   │   │   │   └── weather.py      # Open-Meteo
│   │   │   └── workers/
│   │   │       ├── __main__.py     # 独立调度进程入口
│   │   │       ├── scheduler.py
│   │   │       └── jobs/daily_suggestion.py
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── unit/               # 校验器、路由、隐私判定
│   │       ├── integration/        # DB 事务、幂等、越权
│   │       └── e2e/
│   │
│   └── web/                        # ── Next.js 前端 ──
│       ├── package.json
│       ├── app/
│       │   ├── (auth)/login/
│       │   ├── wardrobe/           # 衣柜列表/详情/新增
│       │   ├── recommend/          # 今日推荐
│       │   ├── history/
│       │   └── settings/           # 偏好 + 模型切换 + 隐私模式
│       ├── components/
│       ├── lib/api.ts              # 生成的类型化客户端
│       └── types/api.d.ts          # 由 OpenAPI 生成，不手写
│
├── packages/
│   └── contracts/                  # OpenAPI 契约 → TS 类型 生成脚本
│
├── scripts/                        # 开发辅助（启动、迁移、种子数据）
├── var/                            # 运行期数据，git 忽略
│   └── uploads/{user_id}/
└── .workbuddy/memory/              # 项目记忆（自动维护）
```

**为什么不拆成 N 个独立服务**：单人开发 + 单机部署，微服务只会把调试成本乘以 N。这里是"一个仓库、两个应用、一个数据库、一个 worker"，边界靠目录和依赖规则约束，够了。

---

# D. 开发阶段与依赖关系

## D.1 依赖图

```
        ┌──────────────┐
        │ Phase 0 环境  │ ← 🔴 当前阻塞点，必须先解决
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │ Phase 1 骨架  │  DB + 认证 + 衣柜 CRUD + 图片上传
        │ （垂直切片）   │  ← 不碰 LLM
        └──┬────────┬──┘
           │        │
           ▼        ▼
   ┌────────────┐  ┌──────────────────┐
   │Phase 2 视觉 │  │ Phase 1.5 前端   │  （可与 2/3 并行）
   │ 解析入库     │  │ 衣柜页面跑通      │
   └────┬───────┘  └──────────────────┘
        ▼
   ┌────────────────────┐
   │ Phase 3 推荐 Agent  │  LangGraph + 工具 + 校验器 + 天气
   └──┬──────────────┬──┘
      │              │
      ▼              ▼
┌──────────────┐  ┌────────────────┐
│Phase 4 记忆闭环│  │Phase 5 定时任务 │
│ 偏好/反馈/推断 │  │ 每日建议 + 通知  │
└──────────────┘  └────────────────┘
      └───────┬──────┘
              ▼
        ┌──────────────┐
        │Phase 6 硬化上线│  RLS/审计/E2E/部署
        └──────────────┘
```

**关键路径**：`0 → 1 → 2 → 3 → 5 → 6`

## D.2 阶段表

| 阶段 | 目标 | 输入 | 输出 | 可并行 |
|---|---|---|---|---|
| **P0 环境修复** | 让"能跑"成为事实 | 本报告 | 可用的 PG、启动的 Ollama、git 身份、仓库骨架、`.env.example` | 前端脚手架可并行搭 |
| **P1 垂直切片** | 打通"注册→传图→看到衣柜"全链路 | P0 | 认证、Alembic 初始迁移、items/item_images CRUD、上传与脱敏、10 个 API、越权测试 | 前端页面可同步开发 |
| **P2 视觉解析** | 上传照片自动生成草稿衣物 | P1 | `vision/` 流水线、ModelRouter、草稿确认流、视觉降级路径 | P1.5 前端 |
| **P3 推荐 Agent** | 按天气/场景/衣柜出方案 | P2 | LangGraph 图、3 个工具、item_id 校验器、天气集成、`agent_runs` 轨迹 | P4 的偏好 schema 可先设计 |
| **P4 记忆与反馈** | 让评价影响下一次推荐 | P3 部分 | explicit/inferred 双轨偏好、反馈事件、记忆抽取、偏好注入 | 与 P5 并行 |
| **P5 定时与前端完善** | 每天自动出建议 | P3 | 独立 worker、幂等领取、每日建议、完整前端、模型切换 UI | 与 P4 并行 |
| **P6 硬化** | 可安心长期使用 | P4+P5 | RLS、外发审计、隐私模式全链路、E2E、部署与备份 | — |

## D.3 哪些必须先做，哪些可并行

**必须先完成（有硬依赖，跳过会返工）**：
1. **数据库 schema 与迁移** —— 所有功能的基础，偏好表的 `source` 字段一旦漏了，Phase 4 要重写。
2. **UserContext 与 Repository 模式** —— 事后补数据隔离代价极高（每个查询都要改）。
3. **LLM 适配层与 `ModelProfile.capabilities`** —— 如果先写死某个厂商 SDK，Phase 5 的模型切换会变成重构。
4. **`item_id` 白名单校验器** —— 它是"不推荐不存在的衣服"的唯一保证，必须在 Agent 之前就位。
5. **幂等领取机制** —— 定时任务上线后再补，会有重复推送的历史脏数据。

**可以并行（接口先约定好即可）**：
- 前端页面 ↔ 后端 API（用 OpenAPI 契约解耦，前端可先 mock）
- 图像解析 ↔ 推荐 Agent（共用 `LLMProvider` 协议，互不阻塞）
- 偏好/反馈后端 ↔ 定时任务（唯一交集是 `preferences` 表，先定 schema）
- 天气集成（Open-Meteo 是纯 HTTP，可随时替换为 stub）

---

# E. 主要技术风险及解决方案

## E-01 🔴 内存不足导致"跑不起来"（最高优先级）

**实测**：总计 15.3 GB，当前空闲仅 **4.1 GB**。
**冲突场景**：Docker Desktop（约 1–2 GB） + PostgreSQL（0.3 GB） + Ollama 加载 9B 模型（🔶 约 7–8 GB） + Next.js dev（1–1.5 GB） + FastAPI（0.3 GB） ≈ **超过可用内存**。

**解决方案（按推荐顺序）**：
1. **PostgreSQL 原生安装，不用 Docker**（省 1–2 GB，且避 E-02）。
2. **不要同时跑本地模型和云端模型压测**；本地模型只在"验证 Ollama 通路"时启动。
3. 本地模型改用更小的（3B–4B，量化后约 2–3 GB）作为默认本地档。
4. 关掉 Docker Desktop 常驻自启；Next.js 用 production build 做 E2E 而非 dev server。
5. 🟡 现实判断：**这台机器更适合"云模型为主 + 本地模型仅作离线兜底"**，与最初"在线/本地自由切换"的期待有落差，需你认可。

## E-02 🟡 Docker 可用性存疑

**实测**：Docker CLI `29.7.2` 存在，但 daemon 未运行（`dockerDesktopLinuxEngine` 管道不存在）。
❓ **待确认**：Docker Desktop 的 Linux 引擎依赖 WSL2，我**无法验证**本机 WSL 状态（沙箱策略拦截了 `wsl.exe`，不是你的系统问题）。请你执行 `wsl -l -v` 确认。

**解决方案**：
- **首选**：`winget install PostgreSQL.PostgreSQL.17` 原生安装。优点：轻、启动快、`psql` 直接可用、内存占用小、路径可控。缺点：需手动建库建用户。
- 备选：Docker Desktop（若 WSL2 正常），隔离更干净但吃内存。
- 备选：云 PG（Supabase / Neon 免费档）。优点：零安装、随时可连。缺点：**用户衣物数据出境/出本机**，与隐私目标冲突 —— 仅建议用于早期开发验证，不要存真实数据。
- 保底（不推荐）：SQLite。会引入 `JSONB/数组/并发写/SQL 方言` 的迁移债，Alembic 迁移脚本基本要重写。

## E-03 🔴 本地视觉能力缺失

**实测**：`qwen3.5:9b` 无 projector 层 → 纯文本模型。**当前本机无法完成"看图加衣"。**
**解决方案**：
1. 短期：视觉任务路由到云端视觉模型（受 `PRIVACY_MODE` 约束，只发裁剪后的单品图）。
2. 中期：下载本地 VL 模型（🔶 通常 5–8 GB，需你确认磁盘与内存预算后才能下）。
3. 兜底：本地色彩/品类粗识别 + 用户确认（`vision/fallback.py`）。

## E-04 🟡 LangGraph 抽象成本 vs 收益

`langgraph 1.2.17` 已 GA，API 比 0.x 稳定得多。但 LangGraph 的 State/Checkpointer/异步语义对新手有真实学习曲线，且它的持久化会引入自己的表。
**解决方案**：只用 `StateGraph` + 线性节点 + 一个条件边；**不用** `Checkpointer`（用自有 `agent_runs` 表存轨迹，避免双份状态）；**不用**多智能体、不用 LangGraph Platform。如果 Phase 3 发现图的价值不明显，降级为 200 行的显式 tool loop —— 但**工具定义与校验器不变**，这部分投入不会浪费。

## E-05 🟡 Python 3.13 生态兼容

FastAPI/Pydantic/SQLAlchemy/psycopg 均已支持 3.13（🔶 主流库已适配）。风险主要在边缘库（如某些图像/OCR 库）。
**解决方案**：用 `uv` 建 venv 锁版本；`pyproject.toml` 固定 `requires-python = ">=3.12,<3.14"`；遇到不兼容库优先换库而非降 Python。

## E-06 🟡 前端类型漂移

前后端分离最常见的隐性成本：后端改字段，前端不报错直到运行时。
**解决方案**：FastAPI 自动导出 OpenAPI → 脚本生成 `types/api.d.ts` → 前端不手写 API 类型；CI 校验生成结果有 diff 即失败。

## E-07 🟡 Prompt 注入与工具滥用

用户可能上传含文字的衣服照片（"忽略之前指令…"），或对话中注入指令诱导工具误调用。
**解决方案**：工具参数全部服务端校验并绑定 `ctx.user_id`（模型无法指定"查别人的衣柜"）；图片文字只作为"标签候选"处理，从不进入指令区；写操作类工具（新增/删除衣物）**不在 Agent 工具集内**，只能由 UI 显式调用。

## E-08 🟡 建议生成的质量不可量化

"推荐好不好"无法自动断言，容易陷入调 prompt 的无底洞。
**解决方案**：先定义可测的**硬指标**（结构合法率、item_id 命中率 100%、场景/温度匹配率、生成时延），再用人工小样本评分（每次 20 条，1–5 分）。没有指标就不改 prompt。

## E-09 🟡 单点故障：一条命令跑不起来

Windows 上"先开 PG 服务、再起 worker、再起 API、再起前端"极易出错。
**解决方案**：`scripts/dev.py` 一键编排（检查端口 → 启动依赖 → 分别起进程），并在启动时打印明确的健康检查结果。

---

# F. 每个阶段的验收标准

> 验收原则：**可执行、可复现、失败会红**。不接受"看起来正常"。

## P0 环境修复

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | PostgreSQL 可连 | `psql -U wearmind -d wearmind -c "select version()"` 返回版本号 |
| 2 | Alembic 可用 | `alembic upgrade head` 成功，`\dt` 能看到 `alembic_version` |
| 3 | Ollama 服务 | `curl localhost:11434/api/tags` 返回 200 且含模型列表 |
| 4 | Git 身份 | `git config --global user.name/email` 非空 |
| 5 | 仓库基线 | `git init` + 首次 commit + `.gitignore` 已排除 `.env`/`var/`/`node_modules`/`.venv` |
| 6 | 双端起得来 | `localhost:3000` 与 `localhost:8000/docs` 同时可访问 |

## P1 垂直切片

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | 注册/登录 | 注册→登录→拿到会话 Cookie→访问 `/me` 返回本人信息 |
| 2 | 衣柜 CRUD | 5 个接口全通；`pytest` 覆盖 happy path + 4 类错误输入 |
| 3 | 上传脱敏 | 上传含 GPS 的 JPEG → 存储文件 EXIF 中 **无 GPS 段**（用 Pillow 断言） |
| 4 | 大图限制 | >10MB 或非图片 → 400/413，不写入磁盘 |
| 5 | **越权测试** | 用户 B 访问用户 A 的 item/图片 → 全部 404；测试用例 ≥6 个 |
| 6 | 类型契约 | OpenAPI 导出成功，TS 类型生成无 diff |
| 7 | 不依赖 LLM | 断网/不配 API Key 时 P1 全部功能仍可用 |

## P2 视觉解析

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | 草稿流程 | 传单品照 → 返回 draft（品类/主色/季节）→ 用户确认后才入库 |
| 2 | 结构化校验 | 模型返回非法 JSON 时，重试后仍失败 → 返回可读错误，不落脏数据 |
| 3 | 能力路由 | 请求带 `requires={VISION}` 时，**不会**被路由到 `qwen3.5:9b`（用测试断言） |
| 4 | 降级路径 | 强制只留无视觉模型 → 系统走本地兜底或文字引导，返回 `degraded: true` |
| 5 | 隐私模式 | `local_only` 时，`external_calls` 表**无**图片类记录（用 mock 断言零调用） |
| 6 | 模型切换 | 改配置从云端切到本地，**不改一行代码、不重启**，功能仍可用 |

## P3 推荐 Agent

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | **幻觉零容忍** | 构造"模型输出不存在的 item_id"用例 → 校验器拦截，最终结果 100% 属于该用户衣柜（随机 50 次跑批） |
| 2 | 天气驱动 | 同衣柜、5°C vs 30°C 两次请求 → 推荐品类有可观察差异（断言冬/夏类目） |
| 3 | 轨迹可追溯 | 每次执行 `agent_runs` 有完整 step 记录（模型、工具、耗时、结果） |
| 4 | 失败可降级 | mock 模型超时 → 返回 503 + 规则推荐，UI 不白屏 |
| 5 | 时延预算 | P95 生成时延 < 15s（云端），超时按预算中断并降级 |
| 6 | 只读安全 | Agent 工具集内**不存在**写操作工具（用测试断言工具清单） |

## P4 记忆与反馈

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | 双轨区分 | 用户明确说"不穿高跟鞋" → `source=explicit, confidence=1.0` |
| 2 | 推断有条件 | 单次喜欢**不**产生 inferred 偏好；达到阈值次数才写入 |
| 3 | 冲突裁决 | explicit 与 inferred 矛盾时，最终响应只体现 explicit（断言 prompt 组装结果） |
| 4 | 反馈生效 | 对某件标"不喜欢"后，下次同场景推荐中该件出现率显著下降（跑批统计） |
| 5 | 偏好可修正 | 用户删除/修改偏好后，下一次请求即生效（无缓存残留） |
| 6 | 数据可删除 | 删除账号 → 该用户 items/preferences/图片文件全部清除（含磁盘） |

## P5 定时任务

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | **幂等** | 同一 `(user, date, kind)` 并发触发 20 次 → 数据库仅 1 条建议（唯一约束断言） |
| 2 | 进程隔离 | FastAPI 以 `--workers 4` 启动时，**不**产生 4 份调度器 |
| 3 | 崩溃恢复 | 任务执行中 kill 进程 → 重启后不产生重复，且未完成的可重试 |
| 4 | 失败可见 | 单用户生成失败不影响其他用户；`job_runs` 记录错误 |
| 5 | 手动重生成 | 用户主动"换一套" → 版本号 +1，历史保留 |

## P6 硬化

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | 安全基线 | 依赖漏洞扫描无 high；Cookie `httpOnly+Secure+SameSite`；无 key 泄漏在日志 |
| 2 | 隐私全链路 | 三种 `PRIVACY_MODE` 下 `external_calls` 记录符合预期（3 组测试） |
| 3 | E2E | Playwright：注册→传图→确认→看推荐→反馈 全流程通过 |
| 4 | 备份 | 一键备份 DB + uploads，能完整恢复到一个空环境 |
| 5 | 冷启动 | 新机器按 README 30 分钟内跑起来 |

---

# G. 需要你提前准备的事项

## G.1 必须你决策（阻塞 P0/P1）

| # | 决策项 | 选项 | 我的建议 |
|---|---|---|---|
| 1 | **数据库怎么装** | 原生 PG / Docker / 云 PG / SQLite | **原生安装 PostgreSQL 17**（`winget install PostgreSQL.PostgreSQL.17`） |
| 2 | **视觉任务走哪条路** | 云端视觉模型 / 下载本地 VL / 仅文字描述 | **先用云端视觉 + 只发裁剪单品图**，本地 VL 后续再评估 |
| 3 | **云端模型用哪家** | OpenAI / 通义 / DeepSeek / 智谱 / 其他 | 你已有则可直接用；选择依据是"是否支持视觉 + 函数调用" |
| 4 | **PRIVACY_MODE 默认值** | local_only / hybrid / cloud_ok | **hybrid** |
| 5 | **认证方式** | 邮箱密码 / 手机验证码 / 仅本地单用户 | **邮箱密码 + httpOnly Cookie**（单用户阶段先不做找回密码） |
| 6 | **部署目标** | 本机自用 / 局域网 / 公网 | 先本机；公网涉及备案与 TLS，建议 P6 再定 |
| 7 | **城市/时区基准** | 用于天气与"每日建议"触发时刻 | 需明确城市（天气）+ 每日触发时间（如 07:30） |

## G.2 需要你用命令确认（我无法验证）

```bash
# 1) WSL 状态（决定 Docker 是否可用）
wsl -l -v

# 2) VS Code 是否真的装了
where code    # 或手动确认是否用别的编辑器

# 3) 是否已有云端模型 API Key（不需要贴给我，只需告知"有/没有"及其服务商）
```

## G.3 需要准备的软件

| 软件 | 用途 | 备注 |
|---|---|---|
| PostgreSQL 17 | 主数据库 | 安装时记住 `postgres` 超级用户密码 |
| （可选）pgAdmin / DBeaver | 看数据 | 排查问题效率提升明显 |
| VS Code + 扩展 | 开发 | Python、Pylance、ESLint、Tailwind CSS IntelliSense、SQLTools |
| （可选）Ollama VL 模型 | 本地视觉 | 🔶 5–8 GB，需你确认后才下载 |

## G.4 需要准备的 API / 配置

| 项目 | 是否必需 | 说明 |
|---|---|---|
| 云端 LLM API Key | ✅ 必需（若走云端） | 需支持 **vision** 与 **function calling** 的能力项 |
| Open-Meteo | ❌ 无需 Key | 免费、免注册、不追踪，**推荐** |
| 商业天气 API | ❌ 不建议 | 需实名 Key 且会外发位置，与隐私目标冲突 |
| `.env` 变量 | ✅ | `DATABASE_URL`、`LLM_PROVIDER`、`*_API_KEY`、`OLLAMA_BASE_URL`、`PRIVACY_MODE`、`JWT_SECRET` |
| 对象存储 | ❌ 第一版不需要 | 本地磁盘足够；`Storage` 协议已预留 S3 替换点 |

---

# H. 对初始技术方案的修改建议

## H.1 建议保留（改动最小）

| 技术 | 结论 |
|---|---|
| **Next.js + TypeScript** | 保留。Next `16.4.3` / React `19.3.1` 实测可装。 **不要**手动把 TypeScript 升到 7.x，沿用 `create-next-app` 默认版本（🔶 新主版本与 Next 的 peer 兼容性需实测） |
| **FastAPI** | 保留。`0.162.0`，与 Pydantic `2.14.1` 配套 |
| **SQLAlchemy + Alembic** | 保留。`2.1.6` / `1.20.1` |
| **Pytest** | 保留，且**加大投入** —— 校验器、幂等、越权三类测试是本项目的安全网 |
| **PostgreSQL** | 保留概念，**改变安装方式**（见 H.2-1） |

## H.2 建议修改（附理由与替代）

### 1️⃣ PostgreSQL：不用 Docker，改原生安装

- **原因**：实测 Docker daemon 未运行；Docker Desktop 常驻占 1–2 GB，而本机空闲内存仅 4.1 GB；PG 原生安装内存占用约为 Docker 方案的 1/3。
- **替代方案**：`winget install PostgreSQL.PostgreSQL.17`。
- **保留灵活性**：`DATABASE_URL` 走环境变量，将来换 Docker/云 PG **不需要改代码**。测试用独立测试库（或 `pytest-postgresql`）。

### 2️⃣ SQLAlchemy：用同步会话，不用 async

- **原因**：异步 SQLAlchemy 在 FastAPI 里需要处理 session 生命周期、lazy load 陷阱、与 LangGraph 工具（同步函数）的桥接 —— 对单人项目是**纯成本、零收益**（本项目并发量极低，单用户几万行数据）。
- **替代方案**：`SQLAlchemy 2.0+ 同步 Session` + `psycopg[binary] 3.3.x`。FastAPI 的同步端点会自动跑在线程池，性能完全够。
- **预留**：Repository 接口不暴露 Session 细节，将来要异步只改实现。

### 3️⃣ APScheduler：从 FastAPI 移出，改独立 worker

- **原因**：`uvicorn --workers N` 会让进程内调度器触发 N 次 —— 这是"定时任务重复执行"的最常见成因。
- **替代方案**：`python -m app.workers` 单独进程 + 数据库唯一约束做真正守卫。
- **更简单的替代（可选）**：Windows 任务计划程序每天调一次 `POST /internal/jobs/daily-suggestion`（带 `X-Job-Token`）。零常驻进程，但不如 APScheduler 灵活。**第一版我倾向 APScheduler，因为它能顺便支持"每小时重试失败任务"。**

### 4️⃣ LangGraph：限缩使用范围

- **原因**：完整 LangGraph 玩法（多智能体、checkpointer、human-in-the-loop）对第一版是明显的复杂度放大。
- **方案**：只用一个线性 `StateGraph`（4 节点 + 1 条件边），**不用** LangGraph 的持久化（用自己的 `agent_runs`）。
- **简化替代**：若 Phase 3 感觉别扭，退化为显式 tool loop（约 200 行，完全可控）。**工具定义、校验器、Provider 适配层三者在两种方案间通用**，所以这个决策可以推迟到 Phase 3 中期再定 —— 前期投入不会浪费。

### 5️⃣ Ollama：降级为"文本后端"，不承诺视觉

- **原因**：实测本地模型无视觉能力；9B 模型将吃掉近一半可用内存。
- **方案**：`ModelProfile` 里如实标注 `capabilities={TEXT, TOOL_CALLING?}`，路由层据此排除。**不要**在文档里宣称"本地模型也能看图"，否则会变成实现阶段的隐性要求。

## H.3 建议新增（原方案未提，但会明显减少返工）

| 新增项 | 为什么必须有 |
|---|---|
| **`ModelProfile.capabilities` 能力声明** | 没有它，"模型不支持视觉/工具调用"只能靠运行时猜 |
| **`agent_runs` / `tool_calls` 执行轨迹表** | 没有它，Agent 出问题只能靠猜；也是后续调优的唯一数据源 |
| **`job_runs` 幂等表 + `UNIQUE` 约束** | 定时任务的正确性靠它，不是靠调度器 |
| **`external_calls` 外发审计表** | 隐私承诺要可验证，不能只写在文档里 |
| **OpenAPI → TS 类型生成脚本** | 消除前后端类型漂移 |
| **`PRIVACY_MODE` 三级开关** | 把隐私从"口头承诺"变成"可配置、可测试的行为" |
| **ADRs（架构决策记录）** | 单人项目最容易忘记"当初为什么这么选"，导致反复推翻重来 |
| **越权测试套件** | 数据隔离的**唯一**真实证据 |

## H.4 明确不建议做的（避免过度设计）

| 不做 | 原因 |
|---|---|
| 微服务拆分 | 单机单用户，只会放大调试成本 |
| 向量数据库 / RAG | 衣柜规模（几十到几百件）用 SQL 过滤 + 关键词完全够；引入向量库是纯复杂度 |
| 消息队列（Kafka/Redis） | 没有异步解耦需求；DB 表 + 定时扫描足够 |
| 多智能体协作 | 一个 Agent + 确定性校验器已经能保证正确性 |
| 自研视觉模型 / 微调 | 成本与收益完全不成比例 |
| Kubernetes / 复杂 CI | 第一版目标是"跑起来且正确" |
| 移动端 App | Web 优先，响应式即可 |

---

# I. 停止点：等待你确认的事项

我已完成调研与规划，**未编写任何业务代码，未安装依赖，未修改系统设置**。

进入 Phase 0 前，请确认或回答：

1. **数据库**：同意原生安装 PostgreSQL 17 吗？（挂起则 P1 无法开始）
2. **视觉路线**：云端视觉模型（只发裁剪单品图）是否可接受？用哪家？
3. **内存取舍**：认可"云模型为主、本地模型仅作离线兜底"的定位吗？
4. **VS Code / WSL**：请执行 `where code` 与 `wsl -l -v` 并告知结果。
5. **城市与每日触发时间**：天气依据哪座城市？每天几点生成建议？
6. **认证粒度**：先做单用户本地，还是第一版就要多用户注册？

确认后我将从 **Phase 0（环境修复 + 仓库骨架）** 开始，并在每一步给出可复现的验证命令。
