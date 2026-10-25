"""日志配置。

- text 格式便于本地开发阅读；json 格式便于后续日志采集。
- 每条日志自动带上 request_id，便于串联一次请求的完整链路。
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_request_id() -> str:
    return request_id_ctx.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn 自带 handler 会重复输出，统一交给 root
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
