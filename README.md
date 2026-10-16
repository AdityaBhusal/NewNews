# NewNews — AI news intelligence for Nepal

[![CI](https://github.com/AdityaBhusal/NewNews/actions/workflows/ci.yml/badge.svg)](https://github.com/AdityaBhusal/NewNews/actions/workflows/ci.yml)

NewNews turns raw news material into ready-to-publish, trustworthy news — automatically.
A newsroom hands it whatever is on the desk: a story draft, a photo of a press release, a
scanned newspaper page, an audio clip. NewNews reads it (including Nepali OCR), checks how
credible it looks, tags what and where it is about, matches it to the clients subscribed to
those beats, and pushes it to them the instant it is ready. When the AI is *not sure*, the
item waits for a human editor instead of reaching the feed — *AI gives assessments,
editors give decisions*.

## The pipeline, simply

```mermaid
flowchart LR
    A["Raw input<br/>article · screenshot<br/>scan · audio"] --> B["Extract<br/>PDF text · OCR · transcription"]
    B --> C["Assess<br/>AI credibility"]
    C -->|confident| D["Enrich<br/>topics · places · summary"]
    C -.->|uncertain| R["Human review<br/>approve / reject"]
    R --> D
    D --> E["Match<br/>client subscriptions"]
    E --> F["Deliver<br/>SSE push + REST"]
```

Three promises hold at every step:

- **Nothing uncertain ships** — low-confidence items stop at the review gate, never the feed.
- **Everything is traceable** — one correlation ID per item, one audit row per stage, a strict
  state machine guards every status change.
- **The demo is free and offline** — the default AI is a deterministic stub; live Groq is a
  config switch (`AI_PROVIDER=groq`).

## System choices

| Layer | Choice | Why | Decision |
|---|---|---|---|
| Language / API | **Python 3.13 + FastAPI** | async + typed, OpenAPI out of the box, the richest AI/media ecosystem | [ADR-0001](docs/decisions/ADR-0001.md) |
| Data store | **PostgreSQL** — one database for data *and* queue | JSON columns, `LISTEN/NOTIFY` available later, zero extra infrastructure | [ADR-0002](docs/decisions/ADR-0002.md) |
| Job queue | **Postgres table + `FOR UPDATE SKIP LOCKED`** | retries and dead-letter semantics without Redis/Celery | [ADR-0003](docs/decisions/ADR-0003.md) |
| AI | **Groq** behind a provider interface; deterministic stub by default | free tier; CI and demos at zero cost; provider swappable | [ADR-0004](docs/decisions/ADR-0004.md) |
| Shape | **Modular monolith** — one image, two processes (`api`, `worker`) | separation without microservices | [ADR-0005](docs/decisions/ADR-0005.md) |
| Delivery | **REST pull + SSE push** (200 ms DB poll) | 117 ms measured against a < 2 s budget; no WebSockets needed | [ADR-0006](docs/decisions/ADR-0006.md) |
| Media | **pypdf → Tesseract (`nep`+`eng`) → Groq Whisper**, all in-container | Nepali scans included — even custom-font PDFs whose text layer is mojibake get OCR'd | [FR-15](docs/requirements.md) |

Rejected alternatives (C#/.NET, Node, SQLite, Redis/Celery, local models, WebSockets) and
every full rationale live in [`docs/decisions/`](docs/decisions/README.md).

## Quick start

```bash
cp .env.example .env                      # add GROQ_API_KEY for live AI (optional)
docker compose up --build                 # migrate → api + worker + postgres
docker compose exec api python -m app.seed   # demo client key (printed once)
open http://localhost:8000/docs           # interactive API docs

export KEY=nn_...                         # the key printed above

# ingest a story — then watch it arrive on SSE (< 2 s after becoming eligible)
curl -X POST http://localhost:8000/api/v1/items \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"body":"Kathmandu, 16 October 2026 — ...","source_key":"demo-1"}'
curl -N http://localhost:8000/api/v1/events -H "Authorization: Bearer $KEY"

# tests: unit run offline; integration needs a second Postgres database
TEST_DATABASE_URL=postgresql+psycopg://newnews:newnews@localhost:5432/newnews_test uv run pytest
```

## The API

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/v1/items` | client key | idempotent ingest — `202` new, `200` duplicate |
| `POST /api/v1/items/{id}/media` | client key | attach a file while the item is `received`; extraction runs before assessment |
| `GET /api/v1/news(?ack=true)` | client key | pull feed, acknowledge deliveries |
| `GET /api/v1/items/{id}` | client key | one item with full detail |
| `GET /api/v1/events` | client key | SSE stream — `Last-Event-ID` resume, 15 s heartbeats |
| `POST/GET /api/v1/clients…` | admin key | mint / inspect clients and subscriptions |
| `GET /api/v1/review…` + `approve`/`reject` | admin key | editorial queue for uncertain items |
| `/healthz` · `/readyz` · `/docs` | none | liveness · readiness (redacted DB errors) · OpenAPI |

## Under the hood

- **Stages**: `extract_media → extract → dedupe → validate → enrich → match`. Each stage is a
  job row claimed with `FOR UPDATE SKIP LOCKED`; retries back off exponentially and
  dead-letter into item status `failed`. Only `transition()` may change an item's status
  (`received → processing → validated → enriched → eligible → delivered`, plus `duplicate`,
  `needs_review`, `rejected`, `failed`).
- **Idempotency**: ingest dedupes on `(source_key, sha256(normalized title+body))` with a
  unique constraint and an `IntegrityError` fallback for races; the `dedupe` stage catches
  reworded copies (3-gram shingles, Jaccard ≥ 0.85 → linked `duplicate`).
- **AI as assessment**: one JSON-schema-constrained Groq call produces score, confidence,
  rationale, topics, locations, urgency and summary *together* (route at 0.75 / 0.45;
  input capped at `AI_MAX_INPUT_CHARS=8000` for the free tier's TPM).
- **Media**: PDF text layer first; a scan — or a custom-font layer with code-punctuation
  density > 3 % (Preeti/Krutidev-style encodings) — falls back to rasterizing pages
  (pypdfium2) and OCR. Extracted text is stored on the asset and appended to the body once,
  so dedupe and the AI both see it.
- **SSE**: at-most-once delivery (marked `sent` before the frame is written); the delivery
  ID doubles as the `Last-Event-ID` cursor; pure-ASGI middleware so streams never buffer.
- **Security**: client keys look like `nn_<prefix>_<secret>`, stored as SHA-256 and verified
  with `hmac.compare_digest`; admin routes require `ADMIN_API_KEY`. Every tunable lives in
  `Settings` (`.env.example` lists them all).
- **Observability**: JSON logs; the correlation ID flows header → item → audit rows → worker.

## Tests & CI

77 tests: unit (offline — hashing, state machine, matching, dedupe, mojibake detection, stub
determinism) and integration (schema-per-test Postgres — full pipeline, review workflow,
media upload → extraction, SSE delivery). OCR tests self-skip where `tesseract` is absent and
run inside the Docker image. CI runs lint + the full suite against `postgres:17` (~1 min)
plus a Docker build that verifies `ffmpeg`/`tesseract (nep)` are in the image.

## Project documentation

- **Plan & progress** → [`docs/roadmap.md`](docs/roadmap.md) — milestones, what's done,
  what's next
- [Requirements (FR/NFR)](docs/requirements.md) · [Architecture](docs/architecture.md) ·
  [Data model & state machine](docs/data-model.md)
- [Decisions](docs/decisions/README.md) — ADR-0001…0007 + rejected alternatives
- [Research findings](docs/phase0-findings.md) — verified environment facts from Phase 0

*License: MIT (see `LICENSE`).*
