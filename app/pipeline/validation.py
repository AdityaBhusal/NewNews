"""Stage: AI validation (credibility assessment).

processing -> validated | needs_review | failed

The AI output is an *assessment* with evidence and confidence — never a claim
of proven truth. Routing thresholds come from settings so they can be tuned
without code changes.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import NewsItem
from app.pipeline.ai.base import STATUS_LIKELY, STATUS_UNCERTAIN, STATUS_UNLIKELY, AIProvider
from app.pipeline.audit import record_audit
from app.pipeline.states import ItemStatus, transition

# Minimum provider confidence before an item bypasses the review queue.
MIN_ROUTING_CONFIDENCE = 0.4

# Confidence at or above this renders as "high" certainty on the API badge.
HIGH_CERTAINTY_CONFIDENCE = 0.7


def certainty_label(score: float | None, confidence: float | None) -> str:
    """Plain-language AI certainty for API consumers (badges, UI).

    Derived from the provider's self-reported *confidence* (how sure the model
    is of its own assessment), not the score (how credible the content looks —
    a confident "unlikely" is still high certainty). Thresholds mirror routing:
    below MIN_ROUTING_CONFIDENCE the item could not bypass review on AI alone.
    """
    if score is None or confidence is None:
        return "unassessed"
    if confidence >= HIGH_CERTAINTY_CONFIDENCE:
        return "high"
    if confidence >= MIN_ROUTING_CONFIDENCE:
        return "medium"
    return "low"


async def run(session: AsyncSession, item: NewsItem, provider: AIProvider) -> str | None:
    settings = get_settings()
    text = f"{item.title or ''}\n{item.body}".strip()

    assessment = await provider.assess_credibility(text)

    item.credibility_score = assessment.score
    item.credibility_confidence = assessment.confidence
    item.validation_rationale = "\n".join(assessment.rationale)

    # Label + routing both derive from configured thresholds so they can be
    # tuned without code changes (the provider's own label is advisory).
    if assessment.score >= settings.credibility_verified_threshold:
        label = STATUS_LIKELY
    elif assessment.score >= settings.credibility_review_threshold:
        label = STATUS_UNCERTAIN
    else:
        label = STATUS_UNLIKELY
    item.validation_status = label

    pass_threshold = label == STATUS_LIKELY and assessment.confidence >= MIN_ROUTING_CONFIDENCE

    detail = {
        "provider": provider.name,
        "score": assessment.score,
        "confidence": assessment.confidence,
        "provider_status": assessment.status,
        "status": label,
        "verified_threshold": settings.credibility_verified_threshold,
        "review_threshold": settings.credibility_review_threshold,
        "routing": "validated" if pass_threshold else "needs_review",
        "rationale": assessment.rationale,
    }

    if pass_threshold:
        transition(item, ItemStatus.VALIDATED)
        await record_audit(session, item, stage="validate", event_type="validated", detail=detail)
        return "enrich"

    transition(item, ItemStatus.NEEDS_REVIEW)
    await record_audit(
        session, item, stage="validate", event_type="needs_review", detail=detail
    )
    return None
