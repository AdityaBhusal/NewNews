"""Server-Sent Events delivery: GET /api/v1/events.

Cross-process notification is DB polling every ``SSE_POLL_INTERVAL_MS`` (M1);
Postgres LISTEN/NOTIFY is the planned M3 upgrade. Delivery ids are monotonic
bigints, so ``Last-Event-ID`` resumes the stream without gaps; frames are
marked ``sent`` before they are written (at-most-once on the wire — clients
that need a guarantee re-read ``GET /api/v1/news`` after reconnecting).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client
from app.api.schemas import ItemOut
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.models import Client, Delivery, NewsItem
from app.pipeline.audit import record_audit
from app.pipeline.states import ItemStatus, transition

log = get_logger("newnews.sse")

router = APIRouter(tags=["events"])

STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
}


def _sse_event(*, event_id: int, event: str, data: dict) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _pending_deliveries(
    session: AsyncSession, *, client_id: str, cursor: int
) -> list[tuple[Delivery, NewsItem]]:
    """Newest pending deliveries for a client above the id cursor."""
    return (
        await session.execute(
            select(Delivery, NewsItem)
            .join(NewsItem, NewsItem.id == Delivery.item_id)
            .where(
                Delivery.client_id == client_id,
                Delivery.status == "pending",
                Delivery.id > cursor,
            )
            .order_by(Delivery.id)
        )
    ).all()


async def _delivery_stream(
    *,
    client_id: str,
    cursor: int,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """SSE frames for a client's pending deliveries; ends cleanly on poll failure.

    The stream owns its DB session (not a request-scoped dependency): a
    request session would hold one connection idle-in-transaction for the
    stream's whole life — servers kill those, poisoning the transaction and
    blowing up request teardown with ``PendingRollbackError``. Instead every
    poll commits (connection returns to the pool, ``pool_pre_ping`` revalidates
    the next checkout), and a failed poll rolls back and closes the stream
    cleanly so the client's reconnect logic restores it.
    """
    settings = get_settings()
    async with SessionLocal() as session:
        loop = asyncio.get_running_loop()
        next_heartbeat = loop.time() + settings.heartbeat_interval_s
        while True:
            if await is_disconnected():
                break
            try:
                rows = await _pending_deliveries(session, client_id=client_id, cursor=cursor)
                for delivery, item in rows:
                    payload = ItemOut.model_validate(item)
                    latency_ms = None
                    if delivery.status == "pending":
                        delivery.status = "sent"
                        delivery.channel = "sse"
                        delivery.sent_at = datetime.now(UTC)
                        if item.status == ItemStatus.ELIGIBLE.value:
                            if item.eligible_at is not None:
                                latency_ms = int(
                                    (datetime.now(UTC) - item.eligible_at).total_seconds()
                                    * 1000
                                )
                            transition(item, ItemStatus.DELIVERED)
                            await record_audit(
                                session,
                                item,
                                stage="deliver",
                                event_type="delivered",
                                detail={
                                    "channel": "sse",
                                    "client_id": client_id,
                                    "delivery_id": delivery.id,
                                    "latency_ms": latency_ms,
                                },
                            )
                        await session.commit()
                    cursor = delivery.id
                    if latency_ms is not None:
                        log.info(
                            "item delivered",
                            extra={
                                "event": "delivered",
                                "item_id": item.id,
                                "client_id": client_id,
                                "latency_ms": latency_ms,
                            },
                        )
                    yield _sse_event(
                        event_id=delivery.id,
                        event="news",
                        data={
                            "delivery_id": delivery.id,
                            "item": payload.model_dump(mode="json"),
                        },
                    )
                # Release the read transaction so the connection returns to
                # the pool between polls — an idle-in-transaction connection
                # gets killed by the server and would poison the next poll.
                await session.commit()
            except Exception:  # noqa: BLE001 — end the stream cleanly instead
                log.exception("SSE poll failed; closing stream")
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001 — connection is likely dead
                    log.exception("SSE rollback failed; closing stream")
                break

            if loop.time() >= next_heartbeat:
                yield ": keepalive\n\n"
                next_heartbeat = loop.time() + settings.heartbeat_interval_s

            await asyncio.sleep(settings.sse_poll_interval_s)


@router.get("/events")
async def events(
    request: Request,
    client: Client = Depends(get_current_client),
) -> StreamingResponse:
    """Stream news items matched to the authenticated client as they go eligible."""
    cursor = 0
    resume = request.headers.get("Last-Event-ID") or request.query_params.get("last_event_id")
    if resume and resume.isdigit():
        cursor = int(resume)

    return StreamingResponse(
        _delivery_stream(
            client_id=client.id, cursor=cursor, is_disconnected=request.is_disconnected
        ),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
