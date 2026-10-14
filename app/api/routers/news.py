"""News retrieval: per-client delivery feed + item detail."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client
from app.api.schemas import DeliveryOut, ItemOut, NewsList
from app.core.db import get_session
from app.models import Client, Delivery, NewsItem
from app.pipeline.states import ItemStatus, transition

router = APIRouter(tags=["news"])


@router.get("/news", response_model=NewsList)
async def list_news(
    limit: int = Query(default=50, ge=1, le=200),
    since_id: int = Query(default=0, ge=0, description="Return deliveries with id > since_id"),
    ack: bool = Query(
        default=False,
        description="Mark returned pending deliveries as sent (pull-based clients).",
    ),
    session: AsyncSession = Depends(get_session),
    client: Client = Depends(get_current_client),
) -> NewsList:
    """Items matched to the authenticated client (newest first).

    SSE is the push channel; this endpoint is pull. By default it does not
    mutate delivery state — pass ``ack=true`` to explicitly confirm receipt.
    """
    rows = (
        await session.execute(
            select(Delivery, NewsItem)
            .join(NewsItem, NewsItem.id == Delivery.item_id)
            .where(Delivery.client_id == client.id, Delivery.id > since_id)
            .order_by(Delivery.id.desc())
            .limit(limit)
        )
    ).all()

    deliveries: list[DeliveryOut] = []
    for delivery, item in rows:
        if ack and delivery.status == "pending":
            await _mark_sent(delivery, item, channel="rest")
        deliveries.append(DeliveryOut(delivery_id=delivery.id, item=ItemOut.model_validate(item)))

    if ack:
        await session.commit()

    return NewsList(count=len(deliveries), items=deliveries)


@router.get("/items/{item_id}", response_model=ItemOut)
async def get_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
    client: Client = Depends(get_current_client),  # noqa: ARG001 — auth required
) -> ItemOut:
    """Item detail by id.

    M1 simplification: any active authenticated client may read any item.
    Delivery-scoped access is a later hardening item.
    """
    item = await session.get(NewsItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return ItemOut.model_validate(item)


async def _mark_sent(delivery: Delivery, item: NewsItem, *, channel: str) -> None:
    now = datetime.now(UTC)
    delivery.status = "sent"
    delivery.channel = channel
    delivery.sent_at = now
    if item.status == ItemStatus.ELIGIBLE.value:
        transition(item, ItemStatus.DELIVERED)
