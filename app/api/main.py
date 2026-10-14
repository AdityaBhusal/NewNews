"""FastAPI application factory."""

from __future__ import annotations

import time

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.routers import clients, events, health, ingest, news
from app.core.config import get_settings
from app.core.context import get_correlation_id, new_correlation_id, set_correlation_id
from app.core.logging import get_logger, setup_logging

log = get_logger("newnews.api")


class RequestContextMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware buffering — SSE stays streaming).

    Assigns a correlation id per request, echoes it back in the response
    headers, and logs one structured line per request with duration.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        correlation_id = headers.get("x-correlation-id") or new_correlation_id()
        set_correlation_id(correlation_id)

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append(
                    (b"x-correlation-id", correlation_id.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log.info(
                "request",
                extra={
                    "event": "request",
                    "method": scope.get("method", "-"),
                    "path": scope.get("path", "-"),
                    "code": status_code,
                    "duration_ms": duration_ms,
                    "correlation_id": correlation_id,
                },
            )


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "AI-powered news intelligence pipeline: ingest raw news/media, assess "
            "credibility, enrich with structured metadata, match to clients, and "
            "deliver via REST + Server-Sent Events. AI outputs are assessments, "
            "not proof of truth."
        ),
    )
    application.add_middleware(RequestContextMiddleware)

    application.include_router(health.router)
    application.include_router(ingest.router, prefix=settings.api_prefix)
    application.include_router(news.router, prefix=settings.api_prefix)
    application.include_router(clients.router, prefix=settings.api_prefix)
    application.include_router(events.router, prefix=settings.api_prefix)

    @application.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": settings.app_name,
            "docs": "/docs",
            "health": "/healthz",
            "api": settings.api_prefix,
            "correlation_id": get_correlation_id(),
        }

    return application


app = create_app()
