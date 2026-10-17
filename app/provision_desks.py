"""Provision the 4 demo category desks with fixed, documented keys.

Usage:
    uv run python -m app.provision_desks               # uses DATABASE_URL
    DATABASE_URL=postgresql+psycopg://... uv run python -m app.provision_desks

Why: API keys are random (`secrets.token_urlsafe`) and stored hashed — they are
printed once and never recoverable. The app's desk-bundle picker
(`mobile/lib/bundles.ts`) needs keys that work out of the box, so the demo
desks get **deterministic** keys defined here (same file, same values, any DB).

Idempotent: existing desks (matched by name, e.g. from seed_demo) get their key
rotated to the documented one; missing desks are created with the seed_demo
subscription. DEMO SCOPE — commit-visible keys; rotate before any real use.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_key, key_prefix
from app.models import Client, Subscription
from app.seed_demo import CATEGORIES

# name → fixed key (prefix must stay unique; "desk000N" can never collide with
# the 8-hex-char prefixes generate_api_key() produces).
DESK_KEYS: dict[str, str] = {
    "newspaper-desk": "nn_desk0001_all-news-all-day",
    "radio-tv-desk": "nn_desk0002_breaking-high-urgency",
    "foreign-desk": "nn_desk0003_politics-international",
    "market-desk": "nn_desk0004_economy-markets",
}


async def provision_desks() -> None:
    assert set(DESK_KEYS) == set(CATEGORIES), "desks must match the seed categories"
    async with SessionLocal() as session:
        for name, sub in CATEGORIES.items():
            full_key = DESK_KEYS[name]
            prefix = key_prefix(full_key)
            assert prefix is not None, full_key
            client = (
                (await session.execute(select(Client).where(Client.name == name)))
                .scalars()
                .first()
            )
            if client is None:
                client = Client(
                    name=name, api_key_prefix=prefix, api_key_hash=hash_key(full_key)
                )
                session.add(client)
                await session.flush()
                session.add(Subscription(client_id=client.id, **sub))
                action = "created "
            else:
                client.api_key_prefix = prefix
                client.api_key_hash = hash_key(full_key)
                action = "rotated"
            await session.commit()
            print(f"{action}  {name:16} → {full_key}")


if __name__ == "__main__":
    asyncio.run(provision_desks())
