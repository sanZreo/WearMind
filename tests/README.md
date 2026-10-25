# tests/（根级）

跨应用的端到端测试，与 `apps/api/tests/` 的分工如下：

| 位置 | 内容 | 运行方式 |
|---|---|---|
| `apps/api/tests/` | 后端单元测试与接口契约测试 | `uv run pytest apps/api/tests` |
| `tests/`（此处） | 跨应用 E2E：真实浏览器访问前端 + 真实 HTTP 调后端 | Phase 5 引入 Playwright 后启用 |

## 为什么现在建目录但不写测试

E2E 需要一个稳定的业务流程（登录 → 加衣 → 看推荐 → 反馈）作为断言对象。
Phase 0 连登录都还没有，此时写"打开首页检查标题"之类的测试只是凑数，
维护成本高于收益。等 Phase 3 有完整链路时再落地，测试才有意义。

当前已覆盖的验证在 `apps/api/tests/`：

- `/health` 返回结构化 JSON，且明确区分进程状态与数据库状态
- 未配置数据库时 `/health/ready` 必须返回 503（而不是假装就绪）
- `/health` 响应中不含密码、DSN、API Key
- 404 使用统一错误信封，并带 `request_id`
- 本阶段不得存在任何 agent / recommend 接口
