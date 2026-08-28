"""生成稳定且不回显敏感输入的 HTTP 错误响应。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from coding_agent.services import ApplicationError
from coding_agent.agents.runtime.run_manager import RunManagerError


class ApiError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def install_error_handlers(app: FastAPI) -> None:
    """注册错误处理器，并确保所有响应只包含稳定的公开字段。"""

    # 第一步：领域边界已完成脱敏的错误可直接映射状态码、代码和消息。
    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return _response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request, exc: ApplicationError
    ) -> JSONResponse:
        return _response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RunManagerError)
    async def manager_error_handler(_request: Request, exc: RunManagerError) -> JSONResponse:
        return _response(exc.status_code, exc.code, exc.message)

    # 第二步：请求校验错误只回显字段位置，不回显客户端提交的原始值。
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for item in exc.errors():
            location = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
            if location and location not in fields:
                fields.append(location)
        suffix = f" Invalid field(s): {', '.join(fields)}." if fields else ""
        return _response(422, "invalid_request", "Request validation failed." + suffix)

    # 第三步：框架及未知异常转换为固定消息，避免泄露内部异常文本。
    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _response(404, "route_not_found", "The requested route was not found.")
        if exc.status_code == 405:
            return _response(405, "method_not_allowed", "The HTTP method is not allowed.")
        return _response(exc.status_code, "http_error", "The request could not be completed.")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return _response(500, "internal_server_error", "The server failed unexpectedly.")


__all__ = ["ApiError", "install_error_handlers"]
