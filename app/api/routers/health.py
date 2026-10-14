"""Liveness / readiness probes (unauthenticated)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.core.db import ping_db

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness: process is up and serving requests."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> Response:
    """Readiness: database is reachable."""
    try:
        await ping_db()
    except Exception as exc:  # noqa: BLE001 — report, don't crash
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "detail": type(exc).__name__},
        )
    return JSONResponse(content={"status": "ready"})
