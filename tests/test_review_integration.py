"""Integration: near-duplicate detection + the editorial review queue.

Requires TEST_DATABASE_URL (a disposable Postgres); skips otherwise.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import TEST_DATABASE_URL
from tests.test_pipeline_integration import NEWS_TEXT, SPAM_TEXT, _create_client

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set — integration tests skipped"
)

# Same story as NEWS_TEXT filed by a rival outlet: reworded lede, different headline,
# different source_key — exact-hash dedupe at ingest cannot see it; the dedupe stage must.
REWORDED_BODY = NEWS_TEXT.replace("Rs 250 million", "Rs 300 million")
NEUTRAL_TEXT = (
    "The government announced a new budget plan amid opposition protests in parliament."
)


async def _ingest(api, auth, payload: dict) -> str:
    response = await api.post("/api/v1/items", json=payload, headers=auth)
    assert response.status_code in (202, 200), response.text
    return response.json()["id"]


# --- W4: near-duplicate detection ------------------------------------------------


async def test_reworded_copy_becomes_duplicate(db, api, admin_headers):
    from app.models import NewsItem
    from app.worker.main import drain

    _, auth = await _create_client(api, admin_headers)

    original_id = await _ingest(
        api, auth, {"title": "Kathmandu road budget", "body": NEWS_TEXT, "source_key": "wire-a"}
    )
    await drain(db)

    copy_id = await _ingest(
        api,
        auth,
        {
            "title": "KMC announces big road outlay",
            "body": REWORDED_BODY,
            "source_key": "rival-b",  # different source: ingest hash dedupe won't catch it
            "source": "rival-outlet",
        },
    )
    assert copy_id != original_id
    await drain(db)

    async with db() as session:
        copy = await session.get(NewsItem, copy_id)
        original = await session.get(NewsItem, original_id)
        assert copy.status == "duplicate"
        assert copy.is_duplicate_of == original_id
        assert original.status == "eligible"  # canonical copy untouched

    # The duplicate never reaches a client's news feed.
    response = await api.get("/api/v1/news", headers=auth)
    items = [entry["item"]["id"] for entry in response.json()["items"]]
    assert copy_id not in items


async def test_distinct_articles_are_not_duplicates(db, api, admin_headers):
    from app.worker.main import drain

    _, auth = await _create_client(api, admin_headers)

    first = await _ingest(api, auth, {"body": NEWS_TEXT, "source_key": "a-1"})
    second = await _ingest(
        api,
        auth,
        {
            "body": (
                "Pokhara airport handled a record 412 international flights last month, "
                "the airport authority said, attributing the surge to new regional routes."
            ),
            "source_key": "b-1",
        },
    )
    await drain(db)

    async with db() as session:
        from app.models import NewsItem

        for item_id in (first, second):
            item = await session.get(NewsItem, item_id)
            # Whatever its validation outcome, it must not be flagged as a duplicate.
            assert item.status != "duplicate", item_id
            assert item.is_duplicate_of is None


# --- W5: editorial review queue --------------------------------------------------


async def test_review_queue_requires_admin(db, api, admin_headers):
    from app.worker.main import drain

    _, auth = await _create_client(api, admin_headers)
    item_id = await _ingest(api, auth, {"body": SPAM_TEXT, "source_key": "spam-auth"})
    await drain(db)

    # No key at all -> 403; a *client* key is not an admin key -> 403.
    assert (await api.get("/api/v1/review")).status_code == 403
    assert (await api.get("/api/v1/review", headers=auth)).status_code == 403
    assert (
        await api.post(f"/api/v1/review/{item_id}/reject", json={"reason": "x"}, headers=auth)
    ).status_code == 403
    # The right key works.
    response = await api.get("/api/v1/review", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["count"] >= 1


async def test_reject_is_terminal_and_audited(db, api, admin_headers):
    from app.models import AuditEvent, NewsItem
    from app.worker.main import drain

    _, auth = await _create_client(api, admin_headers)
    item_id = await _ingest(api, auth, {"body": SPAM_TEXT, "source_key": "spam-reject"})
    await drain(db)

    response = await api.post(
        f"/api/v1/review/{item_id}/reject",
        json={"reason": "Advertiser content, not news"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"

    # Terminal: no jobs left to run, never delivered, reason in the audit trail.
    await drain(db)
    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "rejected"
        events = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.item_id == item_id,
                        AuditEvent.event_type == "review_rejected",
                    )
                )
            ).all()
        )
        assert len(events) == 1
        assert events[0].detail["reason"] == "Advertiser content, not news"

    # Deciding twice must conflict (state machine protects us).
    response = await api.post(
        f"/api/v1/review/{item_id}/approve", json={}, headers=admin_headers
    )
    assert response.status_code == 409


async def test_approve_resumes_pipeline_to_delivery(db, api, admin_headers):
    from app.models import AuditEvent, Delivery, NewsItem
    from app.worker.main import drain

    _, auth = await _create_client(api, admin_headers)

    # Neutral text: stub scores 0.55 (uncertain) -> review queue, not the feed.
    item_id = await _ingest(api, auth, {"body": NEUTRAL_TEXT, "source_key": "neutral-1"})
    await drain(db)
    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "needs_review"

    # Editor sees the queue, item detail (with audit timeline), then approves.
    queue = (await api.get("/api/v1/review", headers=admin_headers)).json()
    assert item_id in [entry["id"] for entry in queue["items"]]

    detail = (await api.get(f"/api/v1/review/{item_id}", headers=admin_headers)).json()
    assert detail["item"]["id"] == item_id
    event_types = [event["event_type"] for event in detail["audit"]]
    assert "needs_review" in event_types

    response = await api.post(
        f"/api/v1/review/{item_id}/approve",
        json={"note": "Verified against the ministry's press briefing"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "validated"

    await drain(db)  # enrich -> match (politics/economy topics) -> eligible

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "eligible"
        assert item.eligible_at is not None
        deliveries = list(
            (await session.scalars(select(Delivery).where(Delivery.item_id == item_id))).all()
        )
        assert len(deliveries) == 1
        events = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.item_id == item_id, AuditEvent.event_type == "review_approved"
                    )
                )
            ).all()
        )
        assert events[0].detail["note"] == "Verified against the ministry's press briefing"

    # And the approved item now shows up in the client's news feed.
    response = await api.get("/api/v1/news", headers=auth)
    assert item_id in [entry["item"]["id"] for entry in response.json()["items"]]
