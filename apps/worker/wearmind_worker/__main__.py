"""WearMind 定时任务进程入口（Phase 0 占位）。

设计约定（现在写下来，避免 Phase 5 走弯路）：
1. 调度器必须运行在**独立进程**中，绝不能塞进 FastAPI。
   `uvicorn --workers N` 会让进程内调度器触发 N 次。
2. "不重复执行"的真正保证不是调度器，而是数据库：
   job_runs 的唯一约束 + `INSERT ... ON CONFLICT DO NOTHING` 抢占。
3. 本进程当前**没有**注册任何任务，因此启动后会立即退出并返回非 0，
   避免被误认为"已经在后台正常工作"。
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [worker] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("wearmind.worker")


def main() -> int:
    logger.warning("WearMind worker 已启动，但当前没有任何已注册任务。")
    logger.info("原因：Phase 0 只搭建骨架，定时任务属于 Phase 5。")
    logger.info("计划任务：每日穿搭建议生成（需先完成 Phase 3 推荐 Agent）。")
    logger.info("退出码 0 = 进程正常退出；但这不代表定时任务已就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
