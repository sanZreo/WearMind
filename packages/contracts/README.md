# packages/contracts

前后端接口契约的唯一来源（Phase 0 只建目录，未实现生成器）。

## 计划

1. FastAPI 启动后导出 OpenAPI：
   `curl http://localhost:8000/openapi.json -o docs/api/openapi.json`
2. 用 `openapi-typescript` 生成 `packages/contracts/src/api.d.ts`。
3. 前端 `apps/web` 通过路径引用该类型文件，**不手写接口类型**。

## 为什么 Phase 0 不实现

生成器需要引入 `openapi-typescript` 依赖，而当前阶段还没有任何业务接口，
生成的类型文件只有 `/health`，属于"为了看起来完整而写的空壳"。
等 Phase 1 出现第一组真实业务接口（衣柜 CRUD）时再落地，
届时字段变更能被类型系统立即捕获，收益才是真实的。

## 调整说明

原计划中的 `packages/shared` 被收敛为 `packages/contracts`：
本项目没有需要前后端共享的运行时逻辑（如校验函数），只有类型契约，
单一定位可以让目录职责更清晰。
