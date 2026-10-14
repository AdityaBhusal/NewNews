"""Stage: near-duplicate detection (fuzzy, post-extraction).

processing -> duplicate (>= neardup_threshold vs an existing item: link
is_duplicate_of, never surface twice) — or continue with a `near_duplicate_suspect`
audit flag when similarity sits between the suspect and hard thresholds.

Exact (source_key, content_hash) duplicates are already rejected at ingest; this
stage catches *reworded copies and cross-source copies*. Candidates: recent items
in a bounded window, brute-force Jaccard over token 3-gram shingle sets — honest
and adequate at prototype scale (documented in docs/architecture.md; MinHash LSH
is the scale-out path).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import NewsItem
from app.pipeline.ai.base import AIProvider
from app.pipeline.audit import record_audit
from app.pipeline.hashing import normalize_text
from app.pipeline.states import ItemStatus, transition

SHINGLE_SIZE = 3


def shingles(text: str, n: int = SHINGLE_SIZE) -> set[str]:
    """Token n-gram shingle set over normalized text."""
    tokens = normalize_text(text).split()
    if not tokens:
        return set()
    if len(tokens) <= n:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


async def best_similarity(
    session: AsyncSession, item: NewsItem, own: set[str], own_body: set[str]
) -> tuple[str, float] | None:
    """Best (canonical_id, score) at or above the suspect threshold, else None."""
    settings = get_settings()
    cutoff = func.now() - timedelta(days=settings.neardup_window_days)
    candidates = (
        await session.scalars(
            select(NewsItem)
            .where(
                NewsItem.id != item.id,
                NewsItem.status != ItemStatus.DUPLICATE.value,  # no duplicate chains
                NewsItem.created_at >= cutoff,
            )
            .order_by(desc(NewsItem.created_at))
            .limit(settings.neardup_candidate_limit)
        )
    ).all()

    best: tuple[str, float] | None = None
    for candidate in candidates:
        # Body-first: rival outlets rewrite headlines but keep the copy, so the
        # score is the *max* of body-only and title+body similarity — the title
        # adds signal for short texts without punishing a reworded lede.
        score = max(
            jaccard(own_body, shingles(candidate.body)),
            jaccard(own, shingles(f"{candidate.title or ''}\n{candidate.body}")),
        )
        if score >= settings.neardup_suspect_threshold and (best is None or score > best[1]):
            best = (candidate.id, round(score, 3))
    return best


async def run(session: AsyncSession, item: NewsItem, provider: AIProvider) -> str | None:
    settings = get_settings()
    own = shingles(f"{item.title or ''}\n{item.body}")
    own_body = shingles(item.body)
    best = await best_similarity(session, item, own, own_body)

    if best is not None and best[1] >= settings.neardup_threshold:
        canonical_id, score = best
        item.is_duplicate_of = canonical_id
        transition(item, ItemStatus.DUPLICATE)
        await record_audit(
            session,
            item,
            stage="dedupe",
            event_type="near_duplicate",
            detail={
                "canonical_item_id": canonical_id,
                "similarity": score,
                "threshold": settings.neardup_threshold,
            },
        )
        return None

    if best is not None:
        await record_audit(
            session,
            item,
            stage="dedupe",
            event_type="near_duplicate_suspect",
            detail={
                "canonical_item_id": best[0],
                "similarity": best[1],
                "suspect_threshold": settings.neardup_suspect_threshold,
            },
        )
    else:
        await record_audit(
            session, item, stage="dedupe", event_type="dedupe_passed", detail={}
        )
    return "validate"
