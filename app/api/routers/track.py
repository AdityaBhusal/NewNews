"""Pipeline board: every item + its stage journey, newest first.

`GET /api/v1/track` powers the all-news pipeline viewer (app Track tab and the
`/track` web page). Each entry carries the item plus its audit `event_type`
stream — exactly what's needed to render a per-row stage rail
(Ingest→Extract→Validate→Review→Enrich→Deliver) without N+1 detail calls.
Admin-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas import ItemOut, TrackBoard, TrackEntry
from app.core.db import get_session
from app.models import AuditEvent, NewsItem

router = APIRouter(prefix="/track", tags=["track"])


@router.get("", response_model=TrackBoard)
async def track_board(
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_admin),
) -> TrackBoard:
    """All items with their audit event stream (drives the pipeline board)."""
    limit = max(1, min(limit, 500))
    items = (
        (
            await session.execute(
                select(NewsItem)
                .order_by(desc(NewsItem.created_at), desc(NewsItem.id))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    item_ids = [item.id for item in items]

    events_by_item: dict[str, list[str]] = {item_id: [] for item_id in item_ids}
    if item_ids:
        event_rows = (
            await session.execute(
                select(AuditEvent.item_id, AuditEvent.event_type)
                .where(AuditEvent.item_id.in_(item_ids))
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
        for item_id, event_type in event_rows:
            events_by_item[item_id].append(event_type)

    entries = [
        TrackEntry(
            item=ItemOut.model_validate(item),
            events=events_by_item.get(item.id, []),
        )
        for item in items
    ]
    return TrackBoard(count=len(entries), items=entries)
