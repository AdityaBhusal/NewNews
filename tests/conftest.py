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

# Media uploads go to MEDIA_ROOT (default /data/media — not writable/meaningful on
# a test host). A fresh temp dir per session keeps tests hermetic.
import tempfile  # noqa: E402

os.environ.setdefault("MEDIA_ROOT", tempfile.mkdtemp(prefix="newnews_media_test_"))


def make_pdf_bytes(text: str) -> bytes:
    """Minimal single-page PDF with a real text layer (Helvetica, Latin-1).

    Built by hand so tests don't need a PDF-generation dependency; pypdf reads
    the xref we compute here. Text must be ASCII without parentheses.
    """
    content = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length "
        + str(len(content)).encode()
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()
    return bytes(out)


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
