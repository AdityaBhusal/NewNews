"""Unit + integration: AI certainty label and the editorial-review badge.

Requires TEST_DATABASE_URL for the integration parts (a disposable Postgres);
unit tests run offline.
"""

from __future__ import annotations

import pytest

from app.pipeline.validation import certainty_label
from tests.conftest import TEST_DATABASE_URL

needs_db = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set — integration tests skipped"
)


# --- unit: certainty mapping -------------------------------------------------


def test_certainty_unassessed_without_ai_output():
    assert certainty_label(None, None) == "unassessed"
    assert certainty_label(0.8, None) == "unassessed"
    assert certainty_label(None, 0.9) == "unassessed"


def test_certainty_thresholds():
    assert certainty_label(0.9, 0.95) == "high"
    assert certainty_label(0.9, 0.7) == "high"  # boundary inclusive
    assert certainty_label(0.55, 0.5) == "medium"
    assert certainty_label(0.55, 0.4) == "medium"  # == MIN_ROUTING_CONFIDENCE
    assert certainty_label(0.3, 0.39) == "low"
    assert certainty_label(0.2, 0.0) == "low"


def test_certainty_follows_confidence_not_score():
    # A confident "unlikely" is still high *certainty* about the assessment.
    assert certainty_label(0.1, 0.9) == "high"
    # A high score the model is unsure about stays medium.
    assert certainty_label(0.9, 0.45) == "medium"


# --- integration: badge lifecycle --------------------------------------------


@needs_db
async def test_approve_sets_editorial_badge_that_survives_to_delivery(
    db, api, admin_headers
):
    from app.models import NewsItem
    from app.worker.main import drain
    from tests.test_pipeline_integration import _create_client
    from tests.test_review_integration import NEUTRAL_TEXT

    _, auth = await _create_client(api, admin_headers)
    response = await api.post(
        "/api/v1/items",
        json={"body": NEUTRAL_TEXT, "source_key": "neutral-badge"},
        headers=auth,
    )
    assert response.status_code == 202, response.text
    item_id = response.json()["id"]
    await drain(db)

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "needs_review"
        assert item.editorially_reviewed is False
        assert item.reviewed_at is None

    response = await api.post(
        f"/api/v1/review/{item_id}/approve",
        json={"note": "Editor checked the facts"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["editorially_reviewed"] is True
    assert approved["reviewed_at"] is not None
    assert approved["certainty_label"] in ("low", "medium", "high", "unassessed")

    await drain(db)  # enrich -> match -> eligible

    # Badge + certainty travel with the item to the feed (REST and SSE share ItemOut).
    response = await api.get(f"/api/v1/items/{item_id}", headers=auth)
    assert response.status_code == 200
    fetched = response.json()
    assert fetched["editorially_reviewed"] is True
    assert fetched["reviewed_at"] is not None
    assert fetched["certainty_label"] == approved["certainty_label"]

    response = await api.get("/api/v1/news", headers=auth)
    assert response.status_code == 200
    entries = [e for e in response.json()["items"] if e["item"]["id"] == item_id]
    assert entries, "approved item must reach the feed"
    assert entries[0]["item"]["editorially_reviewed"] is True


@needs_db
async def test_reject_leaves_badge_unset(db, api, admin_headers):
    from app.models import NewsItem
    from app.worker.main import drain
    from tests.test_pipeline_integration import SPAM_TEXT, _create_client

    _, auth = await _create_client(api, admin_headers)
    response = await api.post(
        "/api/v1/items",
        json={"body": SPAM_TEXT, "source_key": "spam-badge-reject"},
        headers=auth,
    )
    item_id = response.json()["id"]
    await drain(db)

    response = await api.post(
        f"/api/v1/review/{item_id}/reject",
        json={"reason": "Not news"},
        headers=admin_headers,
    )
    assert response.status_code == 200

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.editorially_reviewed is False
        assert item.reviewed_at is None
