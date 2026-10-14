"""Media upload (W2) + extraction-first pipeline (W3) integration.

Requires TEST_DATABASE_URL (a disposable Postgres); skips otherwise.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import TEST_DATABASE_URL, make_pdf_bytes

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set — integration tests skipped"
)

PDF_TEXT = (
    "Kathmandu municipal board approved the annual road expansion plan on Tuesday. "
    "Construction across fourteen wards begins next month and runs through the monsoon."
)


async def _create_client(api, admin_headers) -> dict:
    response = await api.post(
        "/api/v1/clients",
        json={"name": "Media Desk", "subscriptions": []},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['api_key']}"}


async def _ingest(api, auth, key: str) -> str:
    response = await api.post(
        "/api/v1/items",
        json={"body": "placeholder pending attached scan", "source_key": key},
        headers=auth,
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def test_upload_requires_client_key(db, api, admin_headers):
    auth = await _create_client(api, admin_headers)
    item_id = await _ingest(api, auth, "media-noauth")

    response = await api.post(
        f"/api/v1/items/{item_id}/media",
        files={"file": ("a.pdf", make_pdf_bytes(PDF_TEXT), "application/pdf")},
    )
    assert response.status_code == 401


async def test_pdf_upload_is_extracted_into_body_before_assessment(db, api, admin_headers):
    from app.models import AuditEvent, MediaAsset, NewsItem
    from app.worker.main import drain

    auth = await _create_client(api, admin_headers)
    item_id = await _ingest(api, auth, "media-pdf")

    # Attach while status == received (before drain runs the pipeline).
    response = await api.post(
        f"/api/v1/items/{item_id}/media",
        files={"file": ("budget.pdf", make_pdf_bytes(PDF_TEXT), "application/pdf")},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    uploaded = response.json()
    assert uploaded["kind"] == "document"
    assert uploaded["extraction_status"] == "pending"
    assert uploaded["size_bytes"] > 0

    assert await drain(db) >= 1

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "eligible"  # media text fed the whole pipeline
        assert "road expansion plan" in item.body
        assert "[budget.pdf — extracted text]" in item.body

        asset = (
            await session.scalars(select(MediaAsset).where(MediaAsset.item_id == item_id))
        ).one()
        assert asset.extraction_status == "extracted"
        assert "municipal board" in (asset.extracted_text or "")
        assert asset.error is None

        types = [
            e.event_type
            for e in (
                await session.scalars(
                    select(AuditEvent).where(AuditEvent.item_id == item_id)
                )
            ).all()
        ]
        assert "media_attached" in types
        assert "media_extracted" in types


async def test_upload_after_processing_is_rejected(db, api, admin_headers):
    from app.worker.main import drain

    auth = await _create_client(api, admin_headers)
    item_id = await _ingest(api, auth, "media-late")
    await drain(db)

    response = await api.post(
        f"/api/v1/items/{item_id}/media",
        files={"file": ("late.pdf", make_pdf_bytes(PDF_TEXT), "application/pdf")},
        headers=auth,
    )
    assert response.status_code == 409
    assert "received" in response.json()["detail"]


async def test_unsupported_media_type_rejected(db, api, admin_headers):
    auth = await _create_client(api, admin_headers)
    item_id = await _ingest(api, auth, "media-415")

    response = await api.post(
        f"/api/v1/items/{item_id}/media",
        files={"file": ("weird.xyz", b"binary-ish", "application/octet-stream")},
        headers=auth,
    )
    assert response.status_code == 415


async def test_oversize_upload_rejected(db, api, admin_headers, monkeypatch):
    from app.core.config import get_settings

    auth = await _create_client(api, admin_headers)
    item_id = await _ingest(api, auth, "media-413")

    monkeypatch.setenv("MEDIA_MAX_BYTES", "10")
    get_settings.cache_clear()
    try:
        response = await api.post(
            f"/api/v1/items/{item_id}/media",
            files={"file": ("big.pdf", make_pdf_bytes(PDF_TEXT), "application/pdf")},
            headers=auth,
        )
        assert response.status_code == 413
    finally:
        monkeypatch.delenv("MEDIA_MAX_BYTES", raising=False)
        get_settings.cache_clear()


async def test_items_without_media_still_flow(db, api, admin_headers):
    """extract_media is a pass-through when nothing is attached (regression)."""
    from app.models import NewsItem
    from app.worker.main import drain

    auth = await _create_client(api, admin_headers)
    response = await api.post(
        "/api/v1/items",
        json={
            "body": (
                "Kathmandu, 12 March 2026 — The Kathmandu Metropolitan City announced "
                "a Rs 250 million budget for road expansion across 14 wards. The "
                "provincial government approved the plan, and officials said "
                "construction begins next month."
            ),
            "source_key": "media-none",
        },
        headers=auth,
    )
    assert response.status_code == 202
    item_id = response.json()["id"]
    await drain(db)

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "eligible"
        assert "[ — extracted text]" not in item.body  # nothing appended
