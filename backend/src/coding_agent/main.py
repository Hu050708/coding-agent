"""仅限本地访问的 Coding Agent Web 服务 FastAPI 组合入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from coding_agent.services import ApplicationServices
from coding_agent.router.errors import install_error_handlers
from coding_agent.router import api_router
from coding_agent.settings import AppSettings, SettingsError
from coding_agent.database import (
    Database,
    create_database,
    interrupt_stale_runs,
    upgrade_database,
)
from coding_agent.repository import PersistenceService
from coding_agent.agents.runtime.agent_runner import AgentRunner, AgentRunnerProtocol
from coding_agent.agents.runtime.run_manager import RunManager
from coding_agent.agents.security import WorkspacePolicy


def _origin_is_local(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "testserver",
    }


def create_app(
    *,
    settings: AppSettings | None = None,
    runner: AgentRunnerProtocol | None = None,
    manager: RunManager | None = None,
    database: Database | None = None,
    persistence: PersistenceService | None = None,
    migrate_database: bool = True,
) -> FastAPI:
    """构建可注入运行器和管理器边界的应用，便于离线测试。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 第一步：加载配置，迁移并检查数据库；注入对象则保留其所有权给调用方。
        effective_settings = settings or AppSettings.from_environment()
        workspace_policy = WorkspacePolicy(effective_settings.allowed_root)
        effective_database = database
        owns_database = effective_database is None
        if effective_database is None:
            if not effective_settings.database_configured:
                raise SettingsError(
                    "CODING_AGENT_DATABASE_URL is required for Coding Agent Web."
                )
            try:
                if migrate_database:
                    upgrade_database(effective_settings.database_url)
                effective_database = create_database(effective_settings.database_url)
                effective_database.healthcheck()
            except Exception:
                raise RuntimeError(
                    "The Coding Agent PostgreSQL database is unavailable or not migrated."
                ) from None
        # 第二步：修复重启前遗留运行，再依次装配持久化、运行管理和应用服务。
        effective_persistence = persistence or PersistenceService(
            effective_database.session_factory
        )
        interrupt_stale_runs(effective_database.session_factory)
        effective_runner = runner or AgentRunner(effective_settings)
        owns_manager = manager is None
        effective_manager = manager or RunManager(
            runner=effective_runner,
            workspace_policy=workspace_policy,
            max_active_runs=effective_settings.max_active_runs,
            max_retained_runs=effective_settings.max_retained_runs,
            event_buffer_size=effective_settings.event_buffer_size,
            approval_timeout_seconds=min(
                effective_settings.approval_timeout_seconds,
                effective_settings.wall_time_seconds,
            ),
            run_deadline_seconds=effective_settings.wall_time_seconds,
        )
        app.state.settings = effective_settings
        app.state.database = effective_database
        app.state.persistence = effective_persistence
        app.state.run_manager = effective_manager
        app.state.services = ApplicationServices.build(
            persistence=effective_persistence,
            manager=effective_manager,
            workspace_policy=workspace_policy,
        )
        # 第三步：所有依赖挂载到 app.state 后才开始接收请求。
        yield
        if owns_manager:
            # 取消是协作式的，因此需先排空有界工作线程，再释放其终态回调使用的数据库；
            # 请求超时和运行墙钟预算共同限制这里的等待时间。
            effective_manager.shutdown(wait=True)
        if owns_database:
            effective_database.dispose()

    # 第四步：配置仅限本机的主机校验、来源检查和浏览器安全响应头。
    application = FastAPI(
        title="Coding Agent Web API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    @application.middleware("http")
    async def local_security_headers(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
            if not _origin_is_local(origin):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "origin_not_allowed",
                            "message": "Only same-machine browser requests are allowed.",
                        }
                    },
                )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    install_error_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()


def serve() -> None:
    """运行受支持的单进程、仅回环地址开发服务器。"""

    import uvicorn

    settings = AppSettings.from_environment()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=True,
    )


if __name__ == "__main__":
    serve()


__all__ = ["app", "create_app", "serve"]
