"""Shared dependencies: authentication (API keys) and current client."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import key_prefix, verify_key
from app.models import Client


def _extract_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token.strip()
    if x_api_key:
        return x_api_key.strip()
    return None


async def get_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key_query: str | None = Query(default=None, alias="api_key"),
) -> str:
    # Precedence: Bearer → X-API-Key → ?api_key=. The query form exists only for
    # browser clients that cannot set headers (EventSource on /events); request
    # logs record scope["path"] without the query string, so keys never land in logs.
    key = _extract_key(authorization, x_api_key) or (api_key_query or "").strip() or None
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key (Authorization: Bearer <key> or X-API-Key)",
        )
    return key


async def get_current_client(
    key: str = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
) -> Client:
    prefix = key_prefix(key)
    if prefix is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed API key")
    client = (
        await session.execute(select(Client).where(Client.api_key_prefix == prefix))
    ).scalar_one_or_none()
    if client is None or not verify_key(key, client.api_key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if not client.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client disabled")
    return client


async def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    admin_key_query: str | None = Query(default=None, alias="admin_key"),
) -> bool:
    """Admin auth: Bearer / X-Admin-Key, plus ``?admin_key=`` for browser
    EventSource (cannot set headers). Request logs record the path only, so
    query keys never land in logs — same precedent as ``?api_key=`` on /events.
    """
    settings = get_settings()
    presented = _extract_key(authorization, x_admin_key) or (admin_key_query or "").strip()
    if presented is None or presented != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    return True
