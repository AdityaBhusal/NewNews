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
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client
from app.api.schemas import ItemOut
from app.core.config import get_settings
from app.core.db import get_session
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


@router.get("/events")
async def events(
    request: Request,
    client: Client = Depends(get_current_client),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream news items matched to the authenticated client as they go eligible."""
    settings = get_settings()

    cursor = 0
    resume = request.headers.get("Last-Event-ID") or request.query_params.get("last_event_id")
    if resume and resume.isdigit():
        cursor = int(resume)

    async def generator():
        nonlocal cursor
        loop = asyncio.get_running_loop()
        next_heartbeat = loop.time() + settings.heartbeat_interval_s
        while True:
            if await request.is_disconnected():
                break
            try:
                rows = (
                    await session.execute(
                        select(Delivery, NewsItem)
                        .join(NewsItem, NewsItem.id == Delivery.item_id)
                        .where(
                            Delivery.client_id == client.id,
                            Delivery.status == "pending",
                            Delivery.id > cursor,
                        )
                        .order_by(Delivery.id)
                    )
                ).all()
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
                                    "client_id": client.id,
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
                                "client_id": client.id,
                                "latency_ms": latency_ms,
                            },
                        )
                    yield _sse_event(
                        event_id=delivery.id,
                        event="news",
                        data={"delivery_id": delivery.id, "item": payload.model_dump(mode="json")},
                    )
            except Exception:  # noqa: BLE001 — never kill the loop silently
                log.exception("SSE poll failed; closing stream")
                break

            if loop.time() >= next_heartbeat:
                yield ": keepalive\n\n"
                next_heartbeat = loop.time() + settings.heartbeat_interval_s

            await asyncio.sleep(settings.sse_poll_interval_s)

    return StreamingResponse(generator(), media_type="text/event-stream", headers=STREAM_HEADERS)
