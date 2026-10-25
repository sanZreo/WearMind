"""统一错误处理。

所有错误响应形状固定为：

    {"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}

这样前端只需写一次错误解析逻辑；同时 500 类错误不会把堆栈或 DSN 泄露给客户端。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    """业务异常基类。抛出它即可得到结构化的错误响应。"""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "服务器内部错误"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Any = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"
    message = "服务配置不完整"


class AuthenticationRequired(AppError):
    """没有可信身份时的统一响应。

    正式认证尚未实现，因此非开发环境一律 401 —— 而不是"降级成某个默认用户"。
    错误文案刻意不区分"没登录"与"身份无效"，避免成为探测手段。
    """

    status_code = 401
    code = "authentication_required"
    message = "需要认证：未提供有效的用户身份"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "资源不存在"


class DatabaseUnavailable(AppError):
    """数据库未配置或不可用。属于服务端问题，与调用方参数无关。"""

    status_code = 503
    code = "database_unavailable"
    message = "数据库不可用"


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": get_request_id(),
        }
    }


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    logger.warning("business error: code=%s message=%s", exc.code, exc.message)
    return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))


async def _http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed", 403: "forbidden"}.get(
        exc.status_code, f"http_{exc.status_code}"
    )
    return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)))


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # errors() 里可能含不可序列化的对象，统一转字符串
    details = [
        {
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_body("validation_error", "请求参数校验失败", details),
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # 只记录堆栈，绝不把堆栈返回给客户端
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content=_body("internal_error", "服务器内部错误"))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
