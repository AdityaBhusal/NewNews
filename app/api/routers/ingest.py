"""Ingestion API: POST /api/v1/items (idempotent, API-key auth)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client
from app.api.schemas import ItemAccepted, ItemCreate
from app.core.context import get_correlation_id, new_correlation_id
from app.core.db import get_session
from app.models import Client, MediaAsset, NewsItem
from app.pipeline.audit import record_audit
from app.pipeline.hashing import content_hash
from app.pipeline.queue import enqueue_job
from app.pipeline.runner import FIRST_STAGE
from app.pipeline.states import ItemStatus

router = APIRouter(prefix="/items", tags=["ingest"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=ItemAccepted)
async def create_item(
    payload: ItemCreate,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    client: Client = Depends(get_current_client),
) -> ItemAccepted:
    """Submit a news item for processing.

    Idempotent on (source_key, content_hash): resubmitting identical content
    returns the existing item with ``duplicate: true`` instead of reprocessing.
    """
    correlation_id = get_correlation_id()
    if not correlation_id or correlation_id == "-":
        correlation_id = request.headers.get("X-Correlation-ID") or new_correlation_id()
    digest = content_hash(payload.title, payload.body)

    existing = (
        await session.execute(
            select(NewsItem).where(
                NewsItem.source_key == payload.source_key,
                NewsItem.content_hash == digest,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Duplicate submission: same source_key + content_hash. Record it, but
        # never create a second item or re-run the pipeline on the existing one.
        await record_audit(
            session,
            existing,
            stage="ingest",
            event_type="duplicate_submission",
            detail={"client_id": client.id, "source_key": payload.source_key},
        )
        response.status_code = status.HTTP_200_OK
        return ItemAccepted(
            id=existing.id,
            status=existing.status,
            correlation_id=existing.correlation_id,
            duplicate=True,
        )

    item = NewsItem(
        correlation_id=correlation_id,
        source_key=payload.source_key,
        content_hash=digest,
        title=payload.title,
        body=payload.body,
        source=payload.source,
        language=payload.language,
        status=ItemStatus.RECEIVED.value,
        raw_payload=payload.model_dump(),
    )
    session.add(item)

    try:
        await session.flush()  # assigns item.id so dependents can reference it

        for media in payload.media:
            session.add(MediaAsset(item_id=item.id, **media.model_dump()))

        await record_audit(
            session,
            item,
            stage="ingest",
            event_type="received",
            detail={"client_id": client.id, "source_key": payload.source_key, "hash": digest},
        )
        enqueue_job(session, item.id, FIRST_STAGE)
        await session.commit()
    except IntegrityError:
        # Concurrent identical submission won the race — return the winner.
        await session.rollback()
        winner = (
            await session.execute(
                select(NewsItem).where(
                    NewsItem.source_key == payload.source_key,
                    NewsItem.content_hash == digest,
                )
            )
        ).scalar_one_or_none()
        if winner is None:
            raise
        response.status_code = status.HTTP_200_OK
        return ItemAccepted(
            id=winner.id,
            status=winner.status,
            correlation_id=winner.correlation_id,
            duplicate=True,
        )

    return ItemAccepted(
        id=item.id,
        status=item.status,
        correlation_id=item.correlation_id,
        duplicate=False,
    )
