"""Pipeline board: every item + its stage journey, newest first.

`GET /api/v1/track` powers the all-news pipeline viewer (app Track tab and the
`/track` web page). Each entry carries the item plus its audit `event_type`
stream — exactly what's needed to render a per-row stage rail
(Ingest→Extract→Validate→Review→Enrich→Deliver) without N+1 detail calls.

`GET /api/v1/track/events` is the live companion: an admin SSE stream that
emits a `board` frame whenever *anything* in the pipeline moves (the watermark
is the `audit_events` row count — every stage transition, review decision, and
delivery stamps one; the table is append-only, so the count is monotonic and
doubles as the SSE event id for `Last-Event-ID` resume). The delivery stream
at `/api/v1/events` only fires per-client on match, so without this, stage
changes were invisible until a manual reload.
Admin-only; auth via header or `?admin_key=` (browser EventSource).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.routers.events import STREAM_HEADERS, _sse_event
from app.api.schemas import ItemOut, TrackBoard, TrackEntry
from app.core.config import get_settings
from app.core.db import SessionLocal, get_session
from app.core.logging import get_logger
from app.models import AuditEvent, NewsItem

log = get_logger("newnews.track")

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


async def _audit_count(session: AsyncSession) -> int:
    """Watermark: rows in the append-only audit trail (monotonic int = SSE id)."""
    row = (await session.execute(select(func.count(AuditEvent.id)))).scalar()
    return int(row or 0)


async def _track_board_stream(
    *,
    resume: str | None,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """SSE frames for pipeline movement; ends cleanly if a poll ever fails.

    The stream owns its DB session and commits after every poll: a shared
    request session would hold one connection idle-in-transaction (killed by
    the server mid-stream, poisoning teardown with ``PendingRollbackError``).
    A failed poll rolls back and ends the stream — the client's reconnect
    logic restores it.
    """
    settings = get_settings()
    if resume is not None and resume.isdigit():
        cursor = int(resume)  # explicit 0 = replay from the start
    else:
        async with SessionLocal() as session:
            cursor = await _audit_count(session)  # connect → only future changes

    async with SessionLocal() as session:
        loop = asyncio.get_running_loop()
        next_heartbeat = loop.time() + settings.heartbeat_interval_s
        while True:
            if await is_disconnected():
                break
            try:
                latest = await _audit_count(session)
                # Commit releases the read transaction so the connection
                # returns to the pool (pre_ping revalidates the next
                # checkout) — an idle-in-transaction connection gets
                # killed by the server and would poison the next poll.
                await session.commit()
                if latest != cursor:
                    cursor = latest
                    yield _sse_event(
                        event_id=cursor,
                        event="board",
                        data={"audit_count": cursor},
                    )
            except Exception:  # noqa: BLE001 — end the stream cleanly instead
                log.exception("track SSE poll failed; closing stream")
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001 — connection is likely dead
                    log.exception("track SSE rollback failed; closing stream")
                break

            if loop.time() >= next_heartbeat:
                yield ": keepalive\n\n"
                next_heartbeat = loop.time() + settings.heartbeat_interval_s

            await asyncio.sleep(settings.sse_poll_interval_s)


@router.get("/events")
async def track_events(
    request: Request,
    _: bool = Depends(require_admin),
) -> StreamingResponse:
    """Live board stream: one `board` frame whenever anything in the pipeline moves.

    Watermark is the ``audit_events`` row count — the table is append-only
    (items are never deleted), so the count rises on every stage transition,
    review decision, duplicate link, and delivery: a change means the board
    must refetch. Resume via ``Last-Event-ID`` (header) or ``?last_event_id=``
    (EventSource); ``0`` replays from the beginning, omitting the cursor
    subscribes to future changes only.
    """
    resume = request.headers.get("Last-Event-ID") or request.query_params.get("last_event_id")
    return StreamingResponse(
        _track_board_stream(resume=resume, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
