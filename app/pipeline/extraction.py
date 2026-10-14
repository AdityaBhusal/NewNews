"""Stage: extraction/processing (text path; media lands in M2).

received -> processing
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NewsItem
from app.pipeline.ai.base import AIProvider
from app.pipeline.audit import record_audit
from app.pipeline.states import ItemStatus, transition

_WHITESPACE = re.compile(r"\s+")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_DEVANAGARI_THRESHOLD = 0.3

def detect_language(text: str) -> str:
    """Rough script-based detection: >=30% Devanagari -> Nepali, else English."""
    if not text:
        return "en"
    devanagari = len(_DEVANAGARI.findall(text))
    return "ne" if devanagari / len(text) >= _DEVANAGARI_THRESHOLD else "en"


async def run(session: AsyncSession, item: NewsItem, provider: AIProvider) -> str | None:
    body = (item.body or "").strip()
    if not body:
        transition(item, ItemStatus.FAILED)
        await record_audit(
            session,
            item,
            stage="extract",
            event_type="extraction_failed",
            detail={"reason": "empty body"},
        )
        return None

    item.body = _WHITESPACE.sub(" ", body)
    if not item.language:
        item.language = detect_language(f"{item.title or ''} {item.body}")

    transition(item, ItemStatus.PROCESSING)
    await record_audit(
        session,
        item,
        stage="extract",
        event_type="extracted",
        detail={"language": item.language, "chars": len(item.body)},
    )
    return "dedupe"
