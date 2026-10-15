"""Liveness / readiness probes (unauthenticated)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.core.db import ping_db

router = APIRouter(tags=["health"])

# Credentials embedded in a connection URL (driver/SQLAlchemy error text can
# quote the URL it failed on — never leak those, even to an unauthenticated probe).
_URL_CREDENTIALS = re.compile(r"://[^/\s@]+@")


def safe_db_error(exc: BaseException) -> str:
    """Error text safe to expose: URL credentials redacted, length-bounded."""
    message = str(exc) or exc.__class__.__name__
    return _URL_CREDENTIALS.sub("://***@", message)[:400]


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness: process is up and serving requests."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> Response:
    """Readiness: database is reachable (error text redacted, for debugging deploys)."""
    try:
        await ping_db()
    except Exception as exc:  # noqa: BLE001 — report, don't crash
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unavailable",
                "detail": f"{type(exc).__name__}: {safe_db_error(exc)}",
            },
        )
    return JSONResponse(content={"status": "ready"})
