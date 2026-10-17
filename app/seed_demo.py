"""Bulk demo seed: 4 category clients + N demo items — none ever enter review.

`DATABASE_URL=... AI_PROVIDER=stub python -m app.seed_demo --count 200`

Two pools only (decision 2026-10-17 — the review queue is for real editorial
work, not demo data):
- **processed** (default 60%): polished wire copy (dated, sourced, long) → the
  stub auto-validates it → `eligible`/`delivered`, deliveries populate the four
  category desks.
- **raw** (default `--raw-share` 40%): rough intake snippets left at `received`
  — ingested but never enqueued, like an unprocessed inbox. Process one via the
  pipeline manually if you like; it will route to review because it is thin.

Clients are idempotent by name (keys print only on creation); items use stable
`seeddemo-{i}` source keys and are skipped when present, so re-runs only fill
gaps. Pool assignment is index-deterministic (every 5th pattern), so re-runs
never flip an existing item's pool.

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

# (headline beat, topic word bucket, secondary topic) — topic words drive the
# four desks: disaster/politics hit radio-TV's high-urgency gate via BREAKING,
# economy hits market-desk, international/politics hit foreign-press.
BEATS = [
    ("cabinet approved flood relief", "disaster", "politics"),
    ("monsoon landslide blocked the highway", "disaster", None),
    ("NEPSE index climbed on a banking rally", "economy", None),
    ("parliament passed the appropriation bill", "politics", None),
    ("police arrested a smuggling ring", "crime", "politics"),
    ("dengue cases rose sharply", "health", None),
]

# Raw-pool snippets: thin on purpose (they never run through the pipeline, so
# their review-worthiness is irrelevant — they are intake backlog).
RAW_SNIPPETS = [
    "Rain in {place} on day {day}.",
    "The {place} meeting ended well.",
    "Power cut in {place} since {day} October.",
    "Festival lights are up in {place}.",
    "Traffic jam near {place} checkpoint {n}.",
    "Water supply off in {place} ward {n}.",
    "Miracle cure! Code {n}, click now!!",
    "VIRAL prize! Code {n}, click!!",
]


def is_raw(index: int, raw_share: float) -> bool:
    """Index-deterministic pool assignment: stable across re-runs.

    With the default 0.4 share, indexes where ``i % 5 < 2`` are raw.
    """
    raw_slots = round(raw_share * 5)
    return index % 5 < raw_slots


def wire_body(rng: random.Random, place: str, beat: str, detail: str, day: int, tag: str) -> str:
    official = rng.choice(OFFICIALS)
    closing = rng.choice(CLOSINGS).format(
        official=official, official_cap=official.capitalize()
    )
    reporter = rng.choice(REPORTERS)
    bureau = rng.choice(PLACES)
    serial = f"{tag}-{rng.randint(1000, 9999)}"
    return (
        f"{place}, {day} October 2026 — {beat} {detail} {closing} "
        f"(Dispatch {serial} filed by {reporter} via the {bureau} bureau.)"
    )


def processed_story(rng: random.Random, tag: str) -> tuple[str, str]:
    """Wire copy that auto-validates under the stub (score ≥ 0.75, conf ≥ 0.4)."""
    place = rng.choice(PLACES)
    day = rng.randint(1, 17)
    beat = rng.choice(BEATS)
    topic_word = {
        "disaster": "flood relief",
        "economy": "market turnover",
        "politics": "the vote count",
        "crime": "the arrests",
        "health": "the hospital admissions",
    }.get(beat[1], "the development")
    amount = rng.randint(20, 900)
    first_settlement = rng.choice(PLACES)
    second_settlement = rng.choice(PLACES)
    body = wire_body(
        rng,
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


def raw_story(rng: random.Random, tag: str) -> tuple[str, str]:
    """Thin intake snippet — left at `received`, never enqueued."""
    place = rng.choice(PLACES)
    snippet = rng.choice(RAW_SNIPPETS).format(
        place=place, day=rng.randint(1, 17), n=rng.randint(1, 99)
    )
    return "Brief intake", f"{snippet} — {tag}."


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


async def seed_items(session, count: int, rng: random.Random, raw_share: float) -> tuple[int, int]:
    created = 0
    raw_created = 0
    for i in range(count):
        source_key = f"seeddemo-{i:04d}"
        exists = (
            await session.execute(select(NewsItem.id).where(NewsItem.source_key == source_key))
        ).first()
        if exists:
            continue
        raw = is_raw(i, raw_share)
        title, body = (
            raw_story(rng, f"s{i:04d}") if raw else processed_story(rng, f"s{i:04d}")
        )
        digest = content_hash(title, body)
        item = NewsItem(
            correlation_id=new_correlation_id(),
            source_key=source_key,
            content_hash=digest,
            title=title,
            body=body,
            source="seed-demo",
            status=ItemStatus.RECEIVED.value,
            raw_payload={"seed": True, "pool": "raw" if raw else "processed"},
        )
        session.add(item)
        await session.flush()
        await record_audit(
            session, item, stage="ingest", event_type="received",
            detail={"source_key": source_key, "seed": True, "pool": "raw" if raw else "processed"},
        )
        if not raw:
            enqueue_job(session, item.id, FIRST_STAGE)
        else:
            raw_created += 1
        await session.commit()
        created += 1
    return created, raw_created


async def sweep_review_queue(session) -> int:
    """Reject any seed item sitting in `needs_review` (audited).

    The stub auto-validates the processed pool, but the live worker may race the
    local drain and score seeds with a real provider (Groq), which can land a
    few below threshold. Demo data never occupies the editorial queue — so any
    straggler is rejected here with a traceable reason instead of crashing the
    run.
    """
    from app.pipeline.states import transition

    ids = (
        await session.execute(
            select(NewsItem.id).where(
                NewsItem.source_key.like("seeddemo-%"),
                NewsItem.status == ItemStatus.NEEDS_REVIEW.value,
            )
        )
    ).scalars().all()
    for item_id in ids:
        item = await session.get(NewsItem, item_id)
        transition(item, ItemStatus.REJECTED)
        await record_audit(
            session,
            item,
            stage="review",
            event_type="review_rejected",
            detail={
                "reason": "seed pool never occupies the review queue (demo data)",
                "seed_cleanup": True,
            },
        )
    await session.commit()
    return len(ids)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--raw-share",
        type=float,
        default=0.4,
        help="Fraction left unprocessed at `received` (never routed to review).",
    )
    args = parser.parse_args()

    setup_logging("INFO")
    rng = random.Random(args.seed)
    async with SessionLocal() as session:
        await ensure_clients(session)
        created, raw_created = await seed_items(session, args.count, rng, args.raw_share)
    print(f"ingested {created} new items ({raw_created} raw intake); draining with stub…")
    # Drain in batches: drain() stops at max_jobs or an empty queue.
    processed = 0
    while True:
        n = await drain(SessionLocal, provider=StubProvider(), max_jobs=500)
        processed += n
        if n == 0:
            break
    print(f"pipeline processed {processed} jobs")

    async with SessionLocal() as session:
        swept = await sweep_review_queue(session)
        if swept:
            print(f"swept {swept} seed stragglers out of review (live worker raced the drain)")
        rows = (
            await session.execute(
                select(NewsItem.status, func.count())
                .where(NewsItem.source_key.like("seeddemo-%"))
                .group_by(NewsItem.status)
            )
        ).all()
        statuses = dict(rows)
        print("seed item statuses:", statuses)
        if statuses.get("needs_review"):
            raise SystemExit(
                "INVARIANT VIOLATED: seed items reached the review queue after sweep — "
                "the demo pools must never route to review."
            )


if __name__ == "__main__":
    asyncio.run(main())
