# ADR 0001：Monorepo 结构 与 uv workspace

- 状态：已采纳
- 日期：2026-10-25
- 阶段：Phase 0

## 背景

项目包含 Next.js 前端、FastAPI 后端、定时任务进程三部分。
需要考虑：仓库怎么切分、Python 依赖怎么管、前端依赖怎么管。

## 决策

**单一仓库 + uv workspace + 单一 `.venv`。**

```
pyproject.toml          # workspace 根，不打包（package = false）
apps/api/pyproject.toml # 成员，可安装包（hatchling，packages = ["app"]）
apps/worker/pyproject.toml # 成员，不打包（Phase 0 无依赖）
apps/web/               # 独立 npm 项目，不参与 Python 依赖
```

依赖命令统一在仓库根执行 `uv sync`，虚拟环境生成在 `E:/WearMind/.venv`。

## 理由

1. **单一虚拟环境**：`apps/worker` 迟早要 import `apps/api` 的 ORM 模型。
   两套 venv 会导致 `psycopg` / `SQLAlchemy` 版本漂移，进而出现
   "worker 写进去的数据 API 读不出来"这类极难排查的问题。
2. **每个 app 仍保留独立 `pyproject.toml`**：依赖边界仍然清晰，
   将来若真要拆服务，成员目录可以整体搬走。
3. **不用 Docker Compose 一键起全栈**：本机 Docker daemon 未运行、内存只有 4.1 GB 空闲，
   容器化只会增加故障面，见 Phase 0 环境报告。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 前端与后端两个独立仓库 | 单人开发，跨仓库同步契约的成本远大于收益 |
| 根目录塞一个 pyproject + 平铺代码 | 前端与后端混在一起，`node_modules` 与 `.venv` 同级易误操作 |
| Nx / Turborepo | Phase 0 只有两个 app，构建编排收益为零，纯增加心智负担 |
| 每个 app 独立 venv | 见理由 1 |

## 后果

- 优点：一条 `uv sync` 管好全部 Python 依赖；版本天然一致。
- 代价：`.venv` 在仓库根，需要确认 `.gitignore` 已排除（已配置）。
- 注意：`apps/api` 以**可安装包**形式存在（editable），因此 `import app` 在任何目录都可用；
  `apps/worker` 不可安装，需在 `apps/worker` 目录下执行 `uv run python -m worker`。
