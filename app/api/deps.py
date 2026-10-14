"""Shared dependencies: authentication (API keys) and current client."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
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
) -> str:
    key = _extract_key(authorization, x_api_key)
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
) -> bool:
    settings = get_settings()
    presented = _extract_key(authorization, x_admin_key)
    if presented is None or presented != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    return True
