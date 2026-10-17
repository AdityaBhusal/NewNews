"""Desk provisioning: deterministic keys, idempotent create/rotate.

The app's bundle picker needs keys that work out of the box on any DB —
provision_desks.py pins them; this locks the contract.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.security import generate_api_key, hash_key, key_prefix
from app.models import Client, Subscription
from app.provision_desks import DESK_KEYS, provision_desks
from app.seed_demo import CATEGORIES


def test_desk_keys_are_unique_and_cover_every_category() -> None:
    prefixes = [key_prefix(key) for key in DESK_KEYS.values()]
    assert all(prefixes)
    assert len(set(prefixes)) == len(prefixes)
    assert set(DESK_KEYS) == set(CATEGORIES)


async def test_provision_creates_desks_with_documented_keys(db) -> None:
    await provision_desks()

    async with db() as session:
        clients = (await session.execute(select(Client))).scalars().all()
        assert {client.name for client in clients} == set(CATEGORIES)
        for client in clients:
            assert client.api_key_hash == hash_key(DESK_KEYS[client.name])
            subs = (
                (
                    await session.execute(
                        select(Subscription).where(Subscription.client_id == client.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(subs) == 1
            assert subs[0].topics == CATEGORIES[client.name]["topics"]
            assert subs[0].min_urgency == CATEGORIES[client.name]["min_urgency"]


async def test_provision_rotates_leftover_random_keys(db) -> None:
    """A desk from an old seed run (random key, lost) gets rotated in place."""
    _full, prefix, key_hash = generate_api_key()
    async with db() as session:
        client = Client(
            name="market-desk", api_key_prefix=prefix, api_key_hash=key_hash
        )
        session.add(client)
        await session.flush()
        session.add(Subscription(client_id=client.id, **CATEGORIES["market-desk"]))
        await session.commit()

    await provision_desks()

    async with db() as session:
        client = (
            (await session.execute(select(Client).where(Client.name == "market-desk")))
            .scalars()
            .one()
        )
        assert client.api_key_hash == hash_key(DESK_KEYS["market-desk"])
        assert client.api_key_prefix == key_prefix(DESK_KEYS["market-desk"])
