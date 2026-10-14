"""Stage: client matching + delivery fan-out.

enriched -> eligible   (delivery rows created; SSE/REST consumers pick them up)
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client, Delivery, NewsItem, Subscription
from app.pipeline.ai.base import URGENCY_RANK, AIProvider
from app.pipeline.audit import record_audit
from app.pipeline.states import ItemStatus, transition


def subscription_matches(
    *,
    sub_topics: list[str],
    sub_locations: list[str],
    sub_exclude_topics: list[str],
    sub_min_urgency: str,
    item_topics: list[str],
    item_locations: list[str],
    item_urgency: str,
) -> bool:
    """Pure matching rule, unit-tested in isolation.

    - Empty sub_topics / sub_locations = "match everything" on that axis.
    - Any excluded topic present -> no match (exclusions win).
    - Item urgency must be >= the subscription's minimum.
    """
    if sub_exclude_topics and set(sub_exclude_topics) & set(item_topics):
        return False
    if sub_topics and not set(sub_topics) & set(item_topics):
        return False
    if sub_locations and not set(sub_locations) & set(item_locations):
        return False
    return URGENCY_RANK.get(item_urgency, 1) >= URGENCY_RANK.get(sub_min_urgency, 1)


async def run(session: AsyncSession, item: NewsItem, provider: AIProvider) -> str | None:
    rows = await session.execute(
        select(Subscription, Client)
        .join(Client, Client.id == Subscription.client_id)
        .where(Subscription.is_active.is_(True), Client.is_active.is_(True))
    )
    subscriptions = rows.all()

    # Idempotency: a retried job must not double-create deliveries.
    existing = set(
        (await session.scalars(select(Delivery.client_id).where(Delivery.item_id == item.id))).all()
    )

    matched_clients: list[str] = []
    for subscription, _client in subscriptions:
        if subscription.client_id in existing:
            continue
        if subscription_matches(
            sub_topics=subscription.topics or [],
            sub_locations=subscription.locations or [],
            sub_exclude_topics=subscription.exclude_topics or [],
            sub_min_urgency=subscription.min_urgency,
            item_topics=item.topics or [],
            item_locations=item.locations or [],
            item_urgency=item.urgency,
        ):
            session.add(Delivery(item_id=item.id, client_id=subscription.client_id))
            matched_clients.append(subscription.client_id)
            existing.add(subscription.client_id)

    transition(item, ItemStatus.ELIGIBLE)
    await record_audit(
        session,
        item,
        stage="match",
        event_type="eligible",
        detail={
            "matched_clients": matched_clients,
            "topics": item.topics,
            "locations": item.locations,
            "urgency": item.urgency,
        },
    )
    return None
