"""生成稳定且不回显敏感输入的 HTTP 错误响应。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from coding_agent.services import ApplicationError
from coding_agent.agents.runtime.run_manager import RunManagerError


class ApiError(RuntimeError):
    """路由需要直接返回稳定公开错误时使用的异常。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        """创建路由层可安全返回的显式 API 错误。

        :param status_code: HTTP 状态码。
        :param code: 稳定机器错误码。
        :param message: 可公开展示的错误说明。
        """

        super().__init__(message)
        # 保存结构化字段，由统一异常处理器直接读取。
        self.status_code = status_code
        self.code = code
        self.message = message


def _response(status_code: int, code: str, message: str) -> JSONResponse:
    """构建统一的错误响应信封。

    :param status_code: HTTP 状态码。
    :param code: 稳定机器错误码。
    :param message: 可公开展示的错误说明。
    :return: ``{"error": ...}`` 结构的 JSON 响应。
    """

    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def install_error_handlers(app: FastAPI) -> None:
    """注册错误处理器，并确保所有响应只包含稳定的公开字段。

    :param app: 待安装全局异常处理器的 FastAPI 应用。
    """

    # 第一步：领域边界已完成脱敏的错误可直接映射状态码、代码和消息。
    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        """将显式路由错误转换为统一 JSON 响应。

        :param _request: 当前请求；处理逻辑无需读取其内容。
        :param exc: 已脱敏的路由错误。
        :return: 结构化错误响应。
        """

        return _response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request, exc: ApplicationError
    ) -> JSONResponse:
        """将应用层错误转换为统一 JSON 响应。

        :param _request: 当前请求；不读取其内容。
        :param exc: 业务服务抛出的稳定错误。
        :return: 结构化错误响应。
        """

        return _response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RunManagerError)
    async def manager_error_handler(_request: Request, exc: RunManagerError) -> JSONResponse:
        """将运行管理器错误转换为统一 JSON 响应。

        :param _request: 当前请求；不读取其内容。
        :param exc: 运行管理器稳定错误。
        :return: 结构化错误响应。
        """

        return _response(exc.status_code, exc.code, exc.message)

    # 第二步：请求校验错误只回显字段位置，不回显客户端提交的原始值。
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """仅公开无效字段位置，不回显客户端原始输入。

        :param _request: 当前请求；不读取其正文。
        :param exc: FastAPI/Pydantic 请求校验错误。
        :return: HTTP 422 结构化错误响应。
        """

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
        """把框架 HTTP 异常映射为固定公开消息。

        :param _request: 当前请求；不读取其内容。
        :param exc: Starlette HTTP 异常。
        :return: 不包含内部异常详情的错误响应。
        """

        if exc.status_code == 404:
            return _response(404, "route_not_found", "The requested route was not found.")
        if exc.status_code == 405:
            return _response(405, "method_not_allowed", "The HTTP method is not allowed.")
        return _response(exc.status_code, "http_error", "The request could not be completed.")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        """隐藏未知异常细节并返回固定服务器错误。

        :param _request: 当前请求；不读取其内容。
        :param _exc: 未预期异常；刻意不向客户端暴露。
        :return: HTTP 500 固定错误响应。
        """

        return _response(500, "internal_server_error", "The server failed unexpectedly.")


__all__ = ["ApiError", "install_error_handlers"]
