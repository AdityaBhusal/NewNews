"""Client management: mint API keys (admin) + inspect the current client."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client, require_admin
from app.api.schemas import ClientCreate, ClientCreated, ClientOut, SubscriptionOut
from app.core.db import get_session
from app.core.security import generate_api_key
from app.models import Client, Subscription

router = APIRouter(prefix="/clients", tags=["clients"])


def _client_out(client: Client, subscriptions: list[Subscription]) -> ClientOut:
    return ClientOut(
        id=client.id,
        name=client.name,
        is_active=client.is_active,
        created_at=client.created_at,
        subscriptions=[
            SubscriptionOut(
                id=sub.id,
                topics=sub.topics or [],
                locations=sub.locations or [],
                exclude_topics=sub.exclude_topics or [],
                min_urgency=sub.min_urgency,
                is_active=sub.is_active,
            )
            for sub in subscriptions
        ],
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ClientCreated)
async def create_client(
    payload: ClientCreate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(require_admin),
) -> ClientCreated:
    """Create a client (and its subscriptions); returns the API key once."""
    full_key, prefix, key_hash = generate_api_key()
    client = Client(name=payload.name, api_key_prefix=prefix, api_key_hash=key_hash)
    session.add(client)
    await session.flush()  # assigns client.id so subscriptions can reference it

    subscriptions = [
        Subscription(
            client_id=client.id,
            topics=sub.topics,
            locations=sub.locations,
            exclude_topics=sub.exclude_topics,
            min_urgency=sub.min_urgency,
        )
        for sub in payload.subscriptions
    ]
    session.add_all(subscriptions)
    await session.commit()
    await session.refresh(client)

    out = _client_out(client, subscriptions)
    return ClientCreated(**out.model_dump(), api_key=full_key)


@router.get("/me", response_model=ClientOut)
async def whoami(
    session: AsyncSession = Depends(get_session),
    client: Client = Depends(get_current_client),
) -> ClientOut:
    subscriptions = list(
        (
            await session.execute(
                select(Subscription).where(Subscription.client_id == client.id)
            )
        ).scalars()
    )
    return _client_out(client, subscriptions)
