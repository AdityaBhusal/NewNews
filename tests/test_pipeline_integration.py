"""End-to-end integration: ingest -> queue -> stages -> matching -> delivery.

Requires TEST_DATABASE_URL (a disposable Postgres); skips otherwise.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set — integration tests skipped"
)

NEWS_TEXT = (
    "Kathmandu, 12 March 2026 — The Kathmandu Metropolitan City on Tuesday announced "
    "a Rs 250 million budget for road expansion across 14 wards. The provincial "
    "government approved the plan, and the Minister for Urban Development said the "
    "construction will begin next month and continue through the monsoon, according "
    "to a press release. Officials said residents of Banepa and Lalitpur should use "
    "alternative routes during the works."
)

SPAM_TEXT = (
    "SHOCKING!!! You won't believe this miracle secret — click here now!! 100% guaranteed!!!"
)


async def _create_client(api, admin_headers, subscriptions=None) -> tuple[str, dict]:
    response = await api.post(
        "/api/v1/clients",
        json={
            "name": "Integration Desk",
            "subscriptions": subscriptions
            or [
                {
                    "topics": ["politics", "economy", "disaster"],
                    "locations": [],
                    "exclude_topics": [],
                    "min_urgency": "normal",
                }
            ],
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    api_key = response.json()["api_key"]
    return api_key, {"Authorization": f"Bearer {api_key}"}


async def test_full_happy_path(db, api, admin_headers):
    from app.models import Delivery, NewsItem
    from app.worker.main import drain

    api_key, auth = await _create_client(api, admin_headers)
    assert api_key.startswith("nn_")

    # --- ingest
    payload = {
        "title": "Kathmandu announces road budget",
        "body": NEWS_TEXT,
        "source_key": "art-1",
        "source": "integration",
    }
    response = await api.post("/api/v1/items", json=payload, headers=auth)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["duplicate"] is False
    item_id = accepted["id"]

    # --- idempotent resubmission
    response = await api.post("/api/v1/items", json=payload, headers=auth)
    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    assert response.json()["id"] == item_id

    # --- run the pipeline inline
    processed = await drain(db)
    assert processed >= 1

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item is not None
        assert item.status == "eligible"
        assert item.eligible_at is not None
        assert item.credibility_score is not None
        assert item.validation_status is not None
        assert "politics" in item.topics
        assert "kathmandu" in item.locations
        assert item.summary
        deliveries = list(
            (
                await session.scalars(
                    select(Delivery).where(Delivery.item_id == item_id)
                )
            ).all()
        )
        assert len(deliveries) == 1
        assert deliveries[0].status == "pending"

    # --- retrieval
    response = await api.get("/api/v1/news", headers=auth)
    assert response.status_code == 200
    news = response.json()
    assert news["count"] == 1
    assert news["items"][0]["delivery_id"] > 0
    assert news["items"][0]["item"]["id"] == item_id

    # --- explicit ack flips item to delivered
    response = await api.get("/api/v1/news?ack=true", headers=auth)
    assert response.status_code == 200

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "delivered"
        assert item.delivered_at is not None


async def test_low_confidence_goes_to_review_not_news(db, api, admin_headers):
    from app.models import Delivery, NewsItem
    from app.worker.main import drain

    _, auth = await _create_client(api, admin_headers)

    response = await api.post(
        "/api/v1/items",
        json={"body": SPAM_TEXT, "source_key": "spam-1"},
        headers=auth,
    )
    assert response.status_code == 202
    item_id = response.json()["id"]

    await drain(db)

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "needs_review"
        assert item.credibility_score < 0.75
        deliveries = list(
            (
                await session.scalars(
                    select(Delivery).where(Delivery.item_id == item_id)
                )
            ).all()
        )
        assert deliveries == []  # never surfaced as verified news

    response = await api.get("/api/v1/news", headers=auth)
    assert response.json()["count"] == 0


async def test_empty_body_fails_cleanly(db, api, admin_headers):
    from app.models import NewsItem, PipelineJob
    from app.worker.main import drain

    _, auth = await _create_client(api, admin_headers)
    response = await api.post(
        "/api/v1/items",
        json={"body": " ", "source_key": "empty-1"},
        headers=auth,
    )
    assert response.status_code == 202
    item_id = response.json()["id"]

    await drain(db)

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "failed"
        jobs = list(
            (
                await session.scalars(
                    select(PipelineJob).where(PipelineJob.item_id == item_id)
                )
            ).all()
        )
        assert all(job.status == "succeeded" for job in jobs)  # handled, not crashed


async def test_no_matching_subscription_still_eligible_without_delivery(db, api, admin_headers):
    from app.models import Delivery, NewsItem
    from app.worker.main import drain

    _, auth = await _create_client(
        api,
        admin_headers,
        subscriptions=[
            {
                "topics": ["sports"],
                "locations": [],
                "exclude_topics": [],
                "min_urgency": "normal",
            }
        ],
    )
    response = await api.post(
        "/api/v1/items",
        json={"body": NEWS_TEXT, "source_key": "art-2"},
        headers=auth,
    )
    item_id = response.json()["id"]

    await drain(db)

    async with db() as session:
        item = await session.get(NewsItem, item_id)
        assert item.status == "eligible"
        deliveries = list(
            (
                await session.scalars(
                    select(Delivery).where(Delivery.item_id == item_id)
                )
            ).all()
        )
        assert deliveries == []


async def test_audit_trail_records_every_stage(db, api, admin_headers):
    from app.models import AuditEvent, NewsItem
    from app.worker.main import drain

    _, auth = await _create_client(api, admin_headers)
    response = await api.post(
        "/api/v1/items",
        json={"body": NEWS_TEXT, "source_key": "art-3"},
        headers=auth,
    )
    item_id = response.json()["id"]

    await drain(db)

    async with db() as session:
        events = list(
            (
                await session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.item_id == item_id)
                    .order_by(AuditEvent.created_at)
                )
            ).all()
        )
        types = [e.event_type for e in events]
        assert "received" in types
        assert "extracted" in types
        assert "validated" in types
        assert "enriched" in types
        assert "eligible" in types
        assert all(e.correlation_id for e in events)

        item = await session.get(NewsItem, item_id)
        assert all(e.correlation_id == item.correlation_id for e in events)
