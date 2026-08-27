"""FastAPI composition root for the local-only ClearLoop Web service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from clearloop.api.errors import install_error_handlers
from clearloop.api.routes import api_router
from clearloop.config import AppSettings
from clearloop.memory import MemoryRepository, MemoryService
from clearloop.runs.agent_runner import AgentRunner, AgentRunnerProtocol
from clearloop.runs.run_manager import RunManager
from clearloop.security import WorkspacePolicy


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
    memory_service: MemoryService | None = None,
) -> FastAPI:
    """Build an app with injectable runner/manager boundaries for offline tests."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        effective_settings = settings or AppSettings.from_environment()
        workspace_policy = WorkspacePolicy(effective_settings.allowed_root)
        effective_memory_service = memory_service
        if effective_memory_service is None:
            try:
                repository = MemoryRepository(effective_settings.data_dir / "clearloop.db")
                repository.initialize()
                effective_memory_service = MemoryService(repository, workspace_policy)
            except Exception:
                # Memory is an optional local aid. Keep normal runs available if
                # its separate store cannot be initialized.
                effective_memory_service = None
        effective_runner = runner or AgentRunner(
            effective_settings,
            memory_service=effective_memory_service,
        )
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
        app.state.run_manager = effective_manager
        app.state.memory_service = effective_memory_service
        yield
        if owns_manager:
            # Cancellation is cooperative. Do not block the ASGI shutdown loop
            # while an in-flight provider request waits for its bounded timeout.
            effective_manager.shutdown(wait=False)

    application = FastAPI(
        title="ClearLoop Web API",
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
    """Run the supported single-process, loopback-only development server."""

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
