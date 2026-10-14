"""Stage: classification / enrichment.

validated -> enriched | needs_review
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NewsItem
from app.pipeline.ai.base import AIProvider
from app.pipeline.audit import record_audit
from app.pipeline.states import ItemStatus, transition


async def run(session: AsyncSession, item: NewsItem, provider: AIProvider) -> str | None:
    text = f"{item.title or ''}\n{item.body}".strip()

    classification = await provider.classify(text)
    locations = await provider.detect_locations(text)
    summary = await provider.summarize(item.body)

    item.topics = classification.topics
    item.locations = locations
    item.urgency = classification.urgency
    item.summary = summary

    detail = {
        "provider": provider.name,
        "topics": item.topics,
        "locations": item.locations,
        "urgency": item.urgency,
        "summary_chars": len(summary or ""),
    }

    if not item.topics and not item.locations:
        # Nothing to match subscriptions against — a human should look at it.
        transition(item, ItemStatus.NEEDS_REVIEW)
        await record_audit(
            session, item, stage="enrich", event_type="needs_review", detail=detail
        )
        return None

    transition(item, ItemStatus.ENRICHED)
    await record_audit(session, item, stage="enrich", event_type="enriched", detail=detail)
    return "match"
