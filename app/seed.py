"""Seed a demo client + subscription: `python -m app.seed`.

Prints the API key exactly once (only its hash is stored).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.logging import setup_logging
from app.core.security import generate_api_key
from app.models import Client, Subscription

DEMO_CLIENT_NAME = "Demo Newsroom"
DEMO_SUBSCRIPTION = {
    "topics": ["politics", "economy", "disaster"],
    "locations": ["kathmandu", "pokhara"],
    "exclude_topics": ["entertainment"],
    "min_urgency": "normal",
}


async def main() -> None:
    setup_logging("INFO")
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(Client).where(Client.name == DEMO_CLIENT_NAME))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"Client already exists: {existing.name} ({existing.id})")
            return

        full_key, prefix, key_hash = generate_api_key()
        client = Client(name=DEMO_CLIENT_NAME, api_key_prefix=prefix, api_key_hash=key_hash)
        session.add(client)
        await session.flush()  # assigns client.id before the FK reference
        session.add(Subscription(client_id=client.id, **DEMO_SUBSCRIPTION))
        await session.commit()

        print(f"Created client: {client.name} ({client.id})")
        print("Subscription:", DEMO_SUBSCRIPTION)
        print()
        print("API key (shown once, store it now):")
        print(f"  {full_key}")


if __name__ == "__main__":
    asyncio.run(main())
