"""Bulk demo seed: 4 category clients + N pipeline-processed items.

`DATABASE_URL=... AI_PROVIDER=stub python -m app.seed_demo --count 200`

Clients are idempotent by name (keys print only on creation); items use stable
`seeddemo-{i}` source keys and are skipped when present, so re-runs only fill
gaps. The pipeline runs locally via `drain()` with the deterministic stub, so a
bulk seed is free and reproducible (`--seed`): high-wire copy auto-validates,
plain bulletins land in the review queue, spam stays low-confidence.

Category → subscription mapping (agreed 2026-10-17):
- newspaper-desk: everything (empty axes, min_urgency low)
- radio-tv-desk: disaster/politics/sports at high urgency (breaking proxy)
- foreign-desk: politics/international, no urgency gate (older OK — nothing expires)
- market-desk: economy (nepse/market/bank/business keywords)
"""

from __future__ import annotations

import argparse
import asyncio
import random

from sqlalchemy import func, select

from app.core.context import new_correlation_id
from app.core.db import SessionLocal
from app.core.logging import setup_logging
from app.core.security import generate_api_key
from app.models import Client, NewsItem, Subscription
from app.pipeline.ai.stub import StubProvider
from app.pipeline.audit import record_audit
from app.pipeline.hashing import content_hash
from app.pipeline.queue import enqueue_job
from app.pipeline.runner import FIRST_STAGE
from app.pipeline.states import ItemStatus
from app.worker.main import drain

CATEGORIES: dict[str, dict] = {
    "newspaper-desk": {"topics": [], "locations": [], "exclude_topics": [], "min_urgency": "low"},
    "radio-tv-desk": {
        "topics": ["disaster", "politics", "sports"],
        "locations": [],
        "exclude_topics": [],
        "min_urgency": "high",
    },
    "foreign-desk": {
        "topics": ["politics", "international"],
        "locations": [],
        "exclude_topics": [],
        "min_urgency": "normal",
    },
    "market-desk": {
        "topics": ["economy"],
        "locations": [],
        "exclude_topics": [],
        "min_urgency": "normal",
    },
}

PLACES = [
    "Kathmandu", "Pokhara", "Lalitpur", "Bhaktapur", "Biratnagar", "Birgunj",
    "Nepalgunj", "Butwal", "Janakpur", "Dharan", "Dhangadhi", "Hetauda",
    "Banepa", "Chitwan", "Mustang", "Dolakha", "Gorkha", "Kaski", "Nuwakot",
    "Solukhumbu",
]
OFFICIALS = [
    "the Home Ministry", "the chief district officer", "the ministry",
    "police headquarters", "the provincial government", "the municipality",
    "the department", "the central bank",
]

CLOSINGS = [
    "Officials confirmed the development in a press release on Tuesday, according to {official}.",
    "The {official} said a detailed statement will follow after the assessment team reports back.",
    "According to {official}, further updates will be issued as the situation develops.",
    "Reporters were briefed by {official} at the scene on Tuesday afternoon.",
    "{official_cap} confirmed the figures and promised a follow-up briefing next week.",
]

REPORTERS = [
    "R. Sharma", "S. Thapa", "A. Gurung", "B. Karki", "D. Rai", "K. Magar",
    "M. Tamang", "N. Shrestha", "P. Adhikari", "S. Basnet", "T. Lama",
    "Y. Pun", "R. Yadav", "S. Maharjan", "A. KC", "D. Bista",
]


def wire_body(place: str, beat: str, detail: str, day: int, tag: str) -> str:
    official = random.choice(OFFICIALS)
    closing = random.choice(CLOSINGS).format(
        official=official, official_cap=official.capitalize()
    )
    reporter = random.choice(REPORTERS)
    bureau = random.choice(PLACES)
    serial = f"{tag}-{random.randint(1000, 9999)}"
    return (
        f"{place}, {day} October 2026 — {beat} {detail} {closing} "
        f"(Dispatch {serial} filed by {reporter} via the {bureau} bureau.)"
    )


def glimpses(rng: random.Random, tag: str) -> tuple[str, str]:
    """(title, body) across the four beats + score tiers."""
    place = rng.choice(PLACES)
    day = rng.randint(1, 17)
    roll = rng.random()
    if roll < 0.30:  # high-wire: auto-validates, certainty high
        beat = rng.choice([
            ("cabinet approved flood relief", "disaster", "politics"),
            ("monsoon landslide blocked the highway", "disaster", None),
            ("NEPSE index climbed on a banking rally", "economy", None),
            ("parliament passed the appropriation bill", "politics", None),
            ("police arrested a smuggling ring", "crime", "politics"),
            ("dengue cases rose sharply", "health", None),
        ])
        topic_word = {"disaster": "flood relief", "economy": "market turnover",
                      "politics": "the vote count", "crime": "the arrests",
                      "health": "the hospital admissions"}.get(beat[1], "the development")
        amount = rng.randint(20, 900)
        first_settlement = rng.choice(PLACES)
        second_settlement = rng.choice(PLACES)
        body = wire_body(
            place,
            f"The {beat[0]} worth {amount} million rupees, ministers said.",
            f"Work on {topic_word} begins next month across settlements "
            f"in {first_settlement} and {second_settlement}.",
            day,
            tag,
        )
        if beat[1] == "disaster" and rng.random() < 0.5:
            body += (
                " BREAKING: rescue teams report people missing "
                "after the urgent landslide, officials said."
            )
        return beat[0].capitalize(), body
    if roll < 0.65:  # plain bulletin: review queue, certainty medium
        subjects = [
            (
                "budget plan",
                "The government announced a new budget plan amid opposition "
                "protests in parliament.",
            ),
            ("bus park", f"A new bus park opened in {place} with room for 300 vehicles."),
            ("gold price", "Gold prices hit a new record in the Nepali market on Friday."),
            (
                "air quality",
                f"Air quality in {place} worsened this week as brick kilns resumed firing.",
            ),
            (
                "border talks",
                "India and Nepal resumed diplomatic talks on border "
                "infrastructure in New Delhi.",
            ),
            ("cricket win", f"Nepal won a last-ball cricket thriller at the {place} stadium."),
            ("school exams", f"Board exams began for 40,000 students across {place} district."),
            ("film award", f"A Nepali film shot in {place} won the jury award at the festival."),
        ]
        title, body = rng.choice(subjects)
        reporter = rng.choice(REPORTERS)
        return title.capitalize(), f"{body} (Note {tag} via {reporter}.)"
    if roll < 0.85:  # short/low: review queue, certainty low
        shorts = [
            f"Rain in {place} on day {day}.",
            f"The {place} meeting ended well.",
            f"Power cut in {place} since {day} October.",
            f"Festival lights are up in {place}.",
            f"Traffic jam near {place} checkpoint {rng.randint(2, 40)}.",
            f"Water supply off in {place} ward {rng.randint(1, 32)}.",
        ]
        reporter = rng.choice(REPORTERS)
        return "Brief update", f"{rng.choice(shorts)} — {reporter}."
    # spam: review queue, certainty low (<50 chars keeps confidence down;
    # unique code per item keeps near-dup away from identical shouters)
    code = rng.randint(1000, 9999)
    spams = [
        f"Miracle cure! Code {code}, click now!!",
        f"VIRAL prize! Code {code}, click!!",
        f"SHOCKING deal! Code {code} guaranteed!!",
        f"Free gold! Code {code}, click here!!",
    ]
    return "SHOCK SHOCK", rng.choice(spams)


async def ensure_clients(session) -> None:
    for name, sub in CATEGORIES.items():
        existing = (
            await session.execute(select(Client).where(Client.name == name))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"client exists: {name} ({existing.id}) — key not recoverable")
            continue
        full_key, prefix, key_hash = generate_api_key()
        client = Client(name=name, api_key_prefix=prefix, api_key_hash=key_hash)
        session.add(client)
        await session.flush()
        session.add(Subscription(client_id=client.id, **sub))
        await session.commit()
        print(f"created client: {name} rule={sub}")
        print(f"  KEY (once): {full_key}")


async def seed_items(session, count: int, rng: random.Random) -> int:
    created = 0
    for i in range(count):
        source_key = f"seeddemo-{i:04d}"
        exists = (
            await session.execute(select(NewsItem.id).where(NewsItem.source_key == source_key))
        ).first()
        if exists:
            continue
        title, body = glimpses(rng, f"s{i:04d}")
        digest = content_hash(title, body)
        item = NewsItem(
            correlation_id=new_correlation_id(),
            source_key=source_key,
            content_hash=digest,
            title=title,
            body=body,
            source="seed-demo",
            status=ItemStatus.RECEIVED.value,
            raw_payload={"seed": True},
        )
        session.add(item)
        await session.flush()
        await record_audit(
            session, item, stage="ingest", event_type="received",
            detail={"source_key": source_key, "seed": True},
        )
        enqueue_job(session, item.id, FIRST_STAGE)
        await session.commit()
        created += 1
    return created


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    setup_logging("INFO")
    rng = random.Random(args.seed)
    async with SessionLocal() as session:
        await ensure_clients(session)
        created = await seed_items(session, args.count, rng)
    print(f"ingested {created} new items; draining with stub…")
    # Drain in batches: drain() stops at max_jobs or an empty queue.
    processed = 0
    while True:
        n = await drain(SessionLocal, provider=StubProvider(), max_jobs=500)
        processed += n
        if n == 0:
            break
    print(f"pipeline processed {processed} jobs")

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(NewsItem.status, func.count()).group_by(NewsItem.status)
            )
        ).all()
        print("item statuses:", dict(rows))


if __name__ == "__main__":
    asyncio.run(main())
