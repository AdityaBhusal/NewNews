"""Editorial review queue (human-in-the-loop): list / approve / reject.

Approving an item is itself a validation: `needs_review -> validated`, then the
pipeline resumes at **enrichment** (re-scoring would return the same number — the
editor's decision is what changed). Rejecting is terminal (`needs_review ->
rejected`); every decision is written to the audit trail with the editor's note.
All routes are admin-only (X-Admin-Key / Bearer admin key).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas import (
    AuditEventOut,
    ItemOut,
    MediaOut,
    ReviewDecision,
    ReviewDetail,
    ReviewQueue,
    ReviewRejection,
)
from app.core.db import get_session
from app.models import AuditEvent, MediaAsset, NewsItem
from app.pipeline.audit import record_audit
from app.pipeline.queue import enqueue_job
from app.pipeline.states import ItemStatus, transition

router = APIRouter(prefix="/review", tags=["review"])

RESUME_STAGE = "enrich"  # approve skips extract/dedupe/validate on purpose


async def _get_item(session: AsyncSession, item_id: str) -> NewsItem:
    item = (
        await session.execute(select(NewsItem).where(NewsItem.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


async def _get_needs_review(session: AsyncSession, item_id: str) -> NewsItem:
    item = await _get_item(session, item_id)
    if item.status != ItemStatus.NEEDS_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Item is {item.status}, not needs_review",
        )
    return item


@router.get("", response_model=ReviewQueue)
async def list_review_queue(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_admin),
) -> ReviewQueue:
    """Items waiting for an editorial decision, newest first."""
    limit = max(1, min(limit, 200))
    rows = (
        await session.execute(
            select(NewsItem)
            .where(NewsItem.status == ItemStatus.NEEDS_REVIEW.value)
            .order_by(desc(NewsItem.created_at))
            .limit(limit)
        )
    ).scalars()
    items = [ItemOut.model_validate(item) for item in rows]
    return ReviewQueue(count=len(items), items=items)


@router.get("/{item_id}", response_model=ReviewDetail)
async def review_item_detail(
    item_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_admin),
) -> ReviewDetail:
    """One item + its full audit timeline (what the AI said, stage by stage)."""
    item = await _get_item(session, item_id)
    events = (
        await session.execute(
            select(AuditEvent)
            .where(AuditEvent.item_id == item_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    ).scalars()
    assets = (
        await session.execute(
            select(MediaAsset)
            .where(MediaAsset.item_id == item_id)
            .order_by(MediaAsset.created_at)
        )
    ).scalars()
    return ReviewDetail(
        item=ItemOut.model_validate(item),
        audit=[AuditEventOut.model_validate(event) for event in events],
        media=[MediaOut.model_validate(asset) for asset in assets],
    )


@router.post("/{item_id}/approve", response_model=ItemOut)
async def approve_item(
    item_id: str,
    payload: ReviewDecision | None = None,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_admin),
) -> ItemOut:
    """Editor verified the item: validate it and resume the pipeline at enrich."""
    item = await _get_needs_review(session, item_id)
    note = payload.note if payload else None
    transition(item, ItemStatus.VALIDATED)
    item.editorially_reviewed = True
    item.reviewed_at = datetime.now(UTC)
    await record_audit(
        session,
        item,
        stage="review",
        event_type="review_approved",
        detail={"note": note, "ai_score": item.credibility_score},
    )
    enqueue_job(session, item.id, RESUME_STAGE)
    await session.commit()
    await session.refresh(item)
    return ItemOut.model_validate(item)


@router.post("/{item_id}/reject", response_model=ItemOut)
async def reject_item(
    item_id: str,
    payload: ReviewRejection,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_admin),
) -> ItemOut:
    """Editor rejected the item: terminal state, never delivered, reason audited."""
    item = await _get_needs_review(session, item_id)
    transition(item, ItemStatus.REJECTED)
    await record_audit(
        session,
        item,
        stage="review",
        event_type="review_rejected",
        detail={"reason": payload.reason, "ai_score": item.credibility_score},
    )
    await session.commit()
    await session.refresh(item)
    return ItemOut.model_validate(item)
