"""Shared fixtures.

Integration tests need a disposable Postgres: set TEST_DATABASE_URL and they
run; without it they skip, keeping unit tests green offline.
"""

from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    # Must happen before any app module (and its settings) is imported.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# Integration tests exercise *pipeline mechanics* deterministically; AI quality is
# covered separately by the live Groq smoke tests (which build their own provider).
os.environ["AI_PROVIDER"] = "stub"


@pytest.fixture
async def db():
    """Schema-per-test: drop + create all tables on the test database."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set — integration tests skipped")

    from app.core.db import SessionLocal, engine
    from app.models import Base

    await engine.dispose()  # connections are bound to the current event loop
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield SessionLocal
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def api_app():
    from app.api.main import create_app

    return create_app()


@pytest.fixture
async def api(api_app):
    """httpx client wired to the ASGI app (no network)."""
    import httpx

    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    from app.core.config import get_settings

    return {"X-Admin-Key": get_settings().admin_api_key}
