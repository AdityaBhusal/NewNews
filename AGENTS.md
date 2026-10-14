# AGENTS.md — NewNews project context (READ BEFORE CHANGING ANY CODE)

> This file is the single source of truth about **what exists, why it is the way it is,
> and what conventions to follow**. Update it whenever a change lands (new module, changed
> endpoint, new setting, decisions reversed). If this file and the code disagree, the code
> wins — then fix this file.

**Status (2026-10-14): M1 complete & verified.** Next: M2 (Groq + media extraction).
Full plan: `README.md` §4 · Detailed docs: `docs/` (requirements, architecture, data-model,
roadmap, decisions/ADR-0001..0006).

---

## 1. What this project is

Prototype AI news-intelligence platform (Nepal): ingest raw news/media → extract → AI
credibility assessment → enrich (topics/locations/urgency/summary) → match to client
subscriptions → deliver via REST + SSE. Built as a technical assessment. **AI outputs are
assessments, never proof of truth** — score/confidence/rationale are stored, editorial
decisions are separate.

## 2. Stack (decided, do not relitigate — see ADRs)

- Python 3.13, FastAPI 0.143 + Uvicorn, Pydantic v2 (pydantic-settings for config)
- SQLAlchemy 2.0 **async** + psycopg3 (`postgresql+psycopg://` URL works for sync AND async —
  Alembic uses the same URL), Alembic migrations
- PostgreSQL: local PG16 on host (dbs `newnews`, `newnews_test` on **localhost:5432**),
  compose `db` service (postgres:17) published on host port **5433** (5432 was taken)
- Job queue = Postgres table + `FOR UPDATE SKIP LOCKED` (no Redis/Celery — ADR-0003)
- AI: provider interface (`app/pipeline/ai/base.py`) + deterministic **stub** (default);
  Groq (OpenAI-compatible) arrives in M2 via `AI_PROVIDER=groq` config switch (ADR-0004)
- Delivery: SSE (`/api/v1/events`) with 200 ms DB polling (M3 → LISTEN/NOTIFY) + REST pull
- Docker: single image for `api` / `worker` / `migrate` (ffmpeg + tesseract eng/nep baked in)
- uv manages deps (`uv sync`), ruff lints (generated `alembic/versions` excluded)

**Rejected (ADR-0001..0006):** C#/.NET, Node, SQLite, Redis/RabbitMQ/Hangfire/Celery,
Ollama/local models, WebSockets/FCM push. User confirmed .NET is out.

## 3. Repository map

```
app/
├── api/
│   ├── main.py            # create_app(); RequestContextMiddleware = PURE ASGI (not
│   │                      #   BaseHTTPMiddleware — that would buffer SSE streams!)
│   ├── schemas.py         # Pydantic req/resp models (ItemOut uses from_attributes)
│   ├── deps.py            # auth: Bearer or X-API-Key → Client; X-Admin-Key → admin
│   └── routers/           # health(/healthz,/readyz), ingest, news, clients, events(SSE)
├── core/                  # config.py (Settings, lru_cache get_settings), db.py (engine,
│                          #   SessionLocal, get_session dep, session_scope), logging.py
│                          #   (JSON logs), context.py (correlation-id contextvar),
│                          #   security.py (nn_<prefix>_<secret> keys, sha256 at rest)
├── pipeline/
│   ├── states.py          # ItemStatus enum + TRANSITIONS map + transition() (stamps
│   │                      #   eligible_at/delivered_at); raises InvalidTransition
│   ├── hashing.py         # normalize (lower+collapse ws) → sha256 title+body
│   ├── extraction.py      # received→processing; empty body → failed; lang detect (≥30%
│   │                      #   Devanagari → "ne")
│   ├── validation.py      # processing→validated|needs_review; LABELS + routing from
│   │                      #   settings thresholds (0.75 verified / 0.45 review) +
│   │                      #   MIN_ROUTING_CONFIDENCE=0.4
│   ├── enrichment.py      # →enriched; zero topics AND locations → needs_review
│   ├── matching.py        # pure subscription_matches() + →eligible, creates Deliveries
│   ├── queue.py           # enqueue_job (max_attempts from settings), claim_job
│   │                      #   (FOR UPDATE SKIP LOCKED), reschedule_job
│   ├── runner.py          # STAGE_HANDLERS registry: extract→validate→enrich→match
│   ├── audit.py           # record_audit() helper
│   └── ai/                # base.py (Protocol + dataclasses + STATUS_* + URGENCY_RANK),
│                          #   stub.py (lexicons, explainable heuristics), factory.py
├── worker/main.py         # claim → handler → next stage; retry w/ exp backoff
│                          #   (base JOB_RETRY_BASE_SECONDS), dead-letter → item failed;
│                          #   seeds correlation contextvar from item; drain() for tests
├── models/                # item.py (NewsItem+MediaAsset), job.py, client.py (Client,
│                          #   Subscription, Delivery), audit.py, base.py (Base+timestamps)
└── seed.py                # python -m app.seed → demo client, prints key ONCE
tests/                     # conftest (db schema-per-test, api, admin_headers fixtures),
                           #   9 modules; integration needs TEST_DATABASE_URL else skips
alembic/                   # env.py reads settings.database_url; initial rev applied
docs/                      # requirements, architecture, data-model, roadmap, ADRs
```

## 4. Invariants & conventions (follow these!)

1. **State machine**: only `transition()` changes `news_items.status`. Never assign directly.
   Terminal: delivered/duplicate/failed. M1 never sets `duplicate` (dedupe happens pre-insert;
   see data-model.md §8 — don't "fix" this).
2. **Idempotency**: ingestion dedupes on `(source_key, content_hash)`; unique constraint +
   IntegrityError fallback for races. Stages must be re-runnable (matching checks existing
   deliveries before insert).
3. **Flush before FK reference**: PK defaults are UUIDs applied at **flush time** — after
   `session.add(parent)` call `await session.flush()` before reading `.id` for children
   (this exact bug was caught in integration tests).
4. **SSE**: pure-ASGI middleware only; deliveries marked `sent` before frame write
   (at-most-once; recovery via `GET /api/v1/news`); delivery PK is a bigint identity =
   SSE event id = `Last-Event-ID` cursor; heartbeat 15 s; 200 ms poll.
5. **Auth**: keys formatted `nn_<prefix>_<secret>`; only sha256 hash stored; lookup by prefix,
   verify with `hmac.compare_digest`. Admin routes need `X-Admin-Key`/Bearer = `ADMIN_API_KEY`.
6. **Settings > hardcoded**: tunables live in `Settings` (see §5). If you add a tunable, read
   it from settings — don't repeat the "config exists but unused" mistake.
7. **Logging**: JSON lines via `app.core.logging`; pass `extra={...}` (allowed keys in
   `_EXTRAS`); correlation id flows: request header → contextvar → response header →
   `news_items.correlation_id` → audit rows → worker logs.
8. **AI = assessment**: persist score, confidence, status, rationale together; low confidence
   routes to `needs_review`, never silently to the news feed.
9. **Tests with any change**: unit tests offline; integration tests against `newnews_test`.
   Both suites + `ruff check .` must be green before declaring done.
10. **Docs sync**: README + docs/ describe reality; update them (and this file) in the same
    change.

## 5. Config (env / `.env`, defaults in `app/core/config.py`)

`DATABASE_URL` · `ADMIN_API_KEY` · `AI_PROVIDER=stub|groq` · `GROQ_API_KEY` ·
`CREDIBILITY_VERIFIED_THRESHOLD=0.75` · `CREDIBILITY_REVIEW_THRESHOLD=0.45` ·
`JOB_MAX_ATTEMPTS=3` · `JOB_RETRY_BASE_SECONDS=5` · `WORKER_POLL_INTERVAL_MS=200` ·
`SSE_POLL_INTERVAL_MS=200` · `MEDIA_ROOT=/data/media` · `TEST_DATABASE_URL` (tests only).

## 6. Commands

```bash
uv sync                                        # deps (uv in ~/.local/bin)
uv run pytest                                  # unit only (integration auto-skips)
TEST_DATABASE_URL=postgresql+psycopg://newnews:newnews@localhost:5432/newnews_test uv run pytest
uv run ruff check . --fix                      # lint (alembic/versions excluded)
uv run alembic revision --autogenerate -m "..." && uv run alembic upgrade head
docker compose up --build                      # migrate runs first, then api+worker
docker compose exec api python -m app.seed     # demo client, key printed once
docker compose exec -T -e TEST_DATABASE_URL=postgresql+psycopg://newnews:newnews@db:5432/newnews_test api pytest
sg docker -c 'docker compose ...'              # if not in docker group in current shell
```

Endpoints: `POST/GET /api/v1/items`, `GET /api/v1/news(?ack=true)`, `GET /api/v1/items/{id}`,
`GET /api/v1/events` (SSE), `POST /api/v1/clients` (admin), `GET /api/v1/clients/me`,
`/healthz`, `/readyz`, `/docs`.

## 7. Verified facts (2026-10-14 run; re-verify if env changes)

- `docker compose ps` → api/worker/db healthy, migrate exit 0
- ffmpeg 7.1.5 + tesseract `eng, nep, osd` inside container
- 42 tests green on host **and** in container; ruff clean
- Live E2E: eligible→SSE receipt measured **117 ms** (budget < 2 s)
- Host PG16 (5432) vs compose PG (5433) — don't cross them

## 8. Known gaps / next steps (M2+)

- **M2**: Groq provider (impl in `ai/groq.py`, flip `AI_PROVIDER`; never commit the key),
  media extraction (PDF/OCR/Whisper → `media_assets`), near-dup detection, review queue
- **M3**: LISTEN/NOTIFY, latency harness p50/p95/p99 (data already in `eligible_at`/
  `delivered_at`), dashboards
- **M4**: Render blueprint, remote Postgres, ephemeral-disk limitation (S3)
- **M5**: `mobile/` Expo app (dir not created yet)
- Minor: `GET /api/v1/items/{id}` is readable by any active client (documented M1
  simplification → per-delivery access control later); worker graceful shutdown flag
  exists but SIGKILL after grace period not configured in compose
- Dev deps (pytest/ruff) are in the image so tests run in-container — acceptable for the
  demo, split into a dev target before production
