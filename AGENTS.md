# AGENTS.md — NewNews project context (READ BEFORE CHANGING ANY CODE)

> This file is the single source of truth about **what exists, why it is the way it is,
> and what conventions to follow**. Update it whenever a change lands (new module, changed
> endpoint, new setting, decisions reversed). If this file and the code disagree, the code
> wins — then fix this file.

**Status (2026-10-17): M1–M2 complete & verified; M4 live — Aiven `newnews` wired,
web service + in-container worker (`scripts/render_start.sh`), remote E2E green,
keep-warm workflow added, AI `certainty_label` + `editorially_reviewed` badge landed.
Remaining: remote media/OCR upload test, audio clip for Whisper, then M3-slim + M5.** README rewritten 2026-10-16
(descriptive, layman→technical; plan/progress in `docs/roadmap.md`).
Full plan: `docs/roadmap.md` · Detailed docs: `docs/` (requirements, architecture, data-model,
deployment, decisions/ADR-0001..0007, phase0-findings).

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
  Groq (OpenAI-compatible) landed M2 W1 via `AI_PROVIDER=groq` (ADR-0004) — 1 structured
  json_schema call per text + TTL cache + Whisper `transcribe()` for media audio;
  **`AI_MAX_INPUT_CHARS=8000`** guards the free-tier 8 K TPM (a 576 K-char body once 413'd)
- Media (M2 W2/W3): pypdf text layer (fonttools for CFF encodings) + pypdfium2 render →
  Tesseract `nep+eng` OCR → Groq Whisper (ffmpeg for video); files on a shared
  api/worker `media_data` volume at `MEDIA_ROOT` (ephemeral on Render → M4 object storage)
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
│   └── routers/           # health(/healthz,/readyz), ingest, media(POST items/{id}/media),
│                          #   news, clients, events(SSE), review(admin: queue/approve/reject),
│                          #   pages(/feed REST demo, /live SSE demo — static HTML, no auth on pages)
│   ├── static/            # feed.html, live.html served by the pages router
├── core/                  # config.py (Settings, lru_cache get_settings), db.py (engine,
│                          #   SessionLocal, get_session dep, session_scope), logging.py
│                          #   (JSON logs), context.py (correlation-id contextvar),
│                          #   security.py (nn_<prefix>_<secret> keys, sha256 at rest)
├── pipeline/
│   ├── states.py          # ItemStatus enum + TRANSITIONS map + transition() (stamps
│   │                      #   eligible_at/delivered_at); raises InvalidTransition
│   ├── hashing.py         # normalize (lower+collapse ws) → sha256 title+body
│   ├── extraction.py      # received→processing; empty body → failed; lang detect (≥30%
│   │                      #   Devanagari → "ne"); next stage = dedupe
│   ├── media_extract.py   # FIRST_STAGE extract_media (status unchanged): PDF text (pypdf)
│   │                      #   → OCR fallback for scans + custom-font mojibake (density >3%),
│   │                      #   image OCR (nep+eng), audio/video → Groq Whisper; text appended
│   │                      #   once to body under "[file — extracted text]"
│   ├── dedupe.py          # processing→duplicate (shingle 3-gram Jaccard ≥ NEARDUP_THRESHOLD
│   │                      #   0.85 → is_duplicate_of linked) or near_duplicate_suspect audit
│   │                      #   (0.6–0.85); body-first scoring; window/limit from settings
│   ├── validation.py      # processing→validated|needs_review; LABELS + routing from
│   │                      #   settings thresholds (0.75 verified / 0.45 review) +
│   │                      #   MIN_ROUTING_CONFIDENCE=0.4
│   ├── enrichment.py      # →enriched; zero topics AND locations → needs_review
│   ├── matching.py        # pure subscription_matches() + →eligible, creates Deliveries
│   ├── queue.py           # enqueue_job (max_attempts from settings), claim_job
│   │                      #   (FOR UPDATE SKIP LOCKED), reschedule_job
│   ├── runner.py          # STAGE_HANDLERS registry: extract_media→extract→dedupe→
│   │                      #   validate→enrich→match; FIRST_STAGE = extract_media
│   ├── audit.py           # record_audit() helper
│   └── ai/                # base.py (Protocol + dataclasses + STATUS_* + URGENCY_RANK),
│                          #   stub.py (lexicons, explainable heuristics), groq.py (real
│                          #   LLM: 1 structured json_schema call/text + TTL cache +
│                          #   translate + Whisper transcribe), factory.py
├── worker/main.py         # claim → handler → next stage; retry w/ exp backoff
│                          #   (base JOB_RETRY_BASE_SECONDS), dead-letter → item failed;
│                          #   seeds correlation contextvar from item; drain() for tests
│                          #   (+ render_start.sh runs it beside the API on Render free tier)
├── models/                # item.py (NewsItem+MediaAsset), job.py, client.py (Client,
│                          #   Subscription, Delivery), audit.py, base.py (Base+timestamps)
└── seed.py                # python -m app.seed → demo client, prints key ONCE
tests/                     # conftest (db schema-per-test, api, admin_headers fixtures,
                           #   make_pdf_bytes PDF builder), 14 modules; integration needs
                           #   TEST_DATABASE_URL else skips; OCR tests skip without tesseract
alembic/                   # env.py reads settings.database_url; initial rev applied
docs/                      # requirements, architecture, data-model, roadmap (plan+progress),
                           #   decisions/ (ADR-0001..0007), phase0-findings
```

## 4. Invariants & conventions (follow these!)

1. **State machine**: only `transition()` changes `news_items.status`. Never assign directly.
   Terminal: delivered/duplicate/rejected/failed. `duplicate` is set by *two* mechanisms:
   pre-insert exact-hash dedupe (no new row) and the `dedupe` stage post-insert (new row →
   `duplicate` + `is_duplicate_of`). See data-model.md §8.
2. **Editorial decisions ≠ AI output**: `needs_review` is resolved only via the admin review
   API — approve = `needs_review → validated` (pipeline resumes at **enrich**, not validate:
   re-scoring would return the same number), reject = `needs_review → rejected` (terminal,
   reason required, audited). Never bounce approved items back to review.
3. **Idempotency**: ingestion dedupes on `(source_key, content_hash)`; unique constraint +
   IntegrityError fallback for races. Stages must be re-runnable (matching checks existing
   deliveries before insert).
4. **Flush before FK reference**: PK defaults are UUIDs applied at **flush time** — after
   `session.add(parent)` call `await session.flush()` before reading `.id` for children
   (this exact bug was caught in integration tests).
5. **SSE**: pure-ASGI middleware only; deliveries marked `sent` before frame write
   (at-most-once; recovery via `GET /api/v1/news`); delivery PK is a bigint identity =
   SSE event id = `Last-Event-ID` cursor; heartbeat 15 s; 200 ms poll.
6. **Auth**: keys formatted `nn_<prefix>_<secret>`; only sha256 hash stored; lookup by prefix,
   verify with `hmac.compare_digest`. Admin routes need `X-Admin-Key`/Bearer = `ADMIN_API_KEY`.
7. **Settings > hardcoded**: tunables live in `Settings` (see §5). If you add a tunable, read
   it from settings — don't repeat the "config exists but unused" mistake.
8. **Logging**: JSON lines via `app.core.logging`; pass `extra={...}` (allowed keys in
   `_EXTRAS`); correlation id flows: request header → contextvar → response header →
   `news_items.correlation_id` → audit rows → worker logs.
9. **AI = assessment**: persist score, confidence, status, rationale together; low confidence
   routes to `needs_review`, never silently to the news feed.
10. **Tests with any change**: unit tests offline; integration tests against `newnews_test`.
    Both suites + `ruff check .` must be green before declaring done.
11. **Docs sync**: README + docs/ describe reality; update them (and this file) in the same
    change.

## 5. Config (env / `.env`, defaults in `app/core/config.py`)

`DATABASE_URL` · `ADMIN_API_KEY` · `AI_PROVIDER=stub|groq` · `GROQ_API_KEY` ·
`GROQ_MODEL` · `GROQ_STT_MODEL=whisper-large-v3` · `AI_MAX_INPUT_CHARS=8000` ·
`CREDIBILITY_VERIFIED_THRESHOLD=0.75` · `CREDIBILITY_REVIEW_THRESHOLD=0.45` ·
`NEARDUP_THRESHOLD=0.85` · `NEARDUP_SUSPECT_THRESHOLD=0.6` · `NEARDUP_WINDOW_DAYS=90` ·
`NEARDUP_CANDIDATE_LIMIT=2000` · `JOB_MAX_ATTEMPTS=3` · `JOB_RETRY_BASE_SECONDS=5` ·
`WORKER_POLL_INTERVAL_MS=200` · `SSE_POLL_INTERVAL_MS=200` · `MEDIA_ROOT=/data/media` ·
`MEDIA_MAX_BYTES=20971520` · `MEDIA_OCR_LANGUAGES=nep+eng` ·
`MEDIA_PDF_TEXT_MIN_CHARS=50` · `MEDIA_PDF_MAX_PAGES=8` · `TEST_DATABASE_URL` (tests only).

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

**CI (GitHub Actions)**: `.github/workflows/ci.yml` runs on push/PR to `main` —
job 1: `ruff` + full `pytest` against a **postgres:17 service container** (fresh
`newnews_test` DB); job 2: `docker build` + verifies `ffmpeg`/`tesseract (nep)` inside the
image. Green checks = M-status visible at a glance. Keep it green (invariant 9).

Endpoints: `POST/GET /api/v1/items`, `POST /api/v1/items/{id}/media` (multipart, must be
`received`), `GET /api/v1/news(?ack=true)`, `GET /api/v1/items/{id}`,
`GET /api/v1/events` (SSE; `?api_key=` query auth for browsers),
`POST /api/v1/clients` (admin), `GET /api/v1/clients/me`,
`GET /api/v1/review` + `GET/POST /api/v1/review/{id}(|approve|reject)` (admin),
`/feed` + `/live` (open demo pages), `/healthz`, `/readyz`, `/docs`.

## 7. Verified facts (2026-10-15 run; re-verify if env changes)

- `docker compose ps` → api/worker/db healthy, migrate exit 0; shared `media_data` volume
  mounted on api+worker at `/data/media`
- ffmpeg 7.1.5 + tesseract `eng, nep, osd` inside container (host has **no** tesseract/ffmpeg
  → those 2 OCR tests skip on host and pass in-container)
- 77 tests total: 75 pass + 2 OCR-skip on host with `TEST_DATABASE_URL`; ruff clean
  (42 M1 + 7 Groq + 12 dedupe/review + 14 media W2/W3 + 2 readyz/redaction)
- Live E2E M1: eligible→SSE receipt measured **117 ms** (budget < 2 s)
- Live E2E M2 media: screenshot PNG → Unicode Devanagari OCR (753 chars); 12.4 MB Gorkhapatra
  PDF (Preeti/custom-font layer → mojibake) → OCR → 133 K chars clean Devanagari → `ne` →
  Groq → `needs_review` → admin approve → Nepali summary + topics → `eligible`
- Groq free tier `openai/gpt-oss-120b` = **8 K TPM** → requests must stay under
  `AI_MAX_INPUT_CHARS=8000` (observed 413 at ~15 K tokens → dead-letter)
- Host PG16 (5432) vs compose PG (5433) — don't cross them

## 8. Known gaps / next steps (M3+)

- **M2 W2/W3 done** (2026-10-15): upload endpoint, `extract_media` FIRST_STAGE, OCR/Whisper,
  `media_data` volume — but **Whisper path is code-complete, not live-tested** (audio clip
  still pending from user). **`GROQ_API_KEY` is in local `.env` — never commit it**
  (`.env` is gitignored; `samples/` too). Documented race: worker may claim `extract_media`
  before a client finishes uploading (attach right after the 202; combined multipart ingest
  deferred to M5). Upload-before-processing means re-uploads after `received` → 409.
- Review-queue UX is API-only (curl/docs); a tiny admin UI could ride on top later.
- **M3**: LISTEN/NOTIFY, latency harness p50/p95/p99 (data already in `eligible_at`/
  `delivered_at`), dashboards
- **M4**: Render blueprint, remote Postgres (Aiven URL sits in `.env` as `DATABASE_URL_AIVEN`,
  scheme must be rewritten `postgres://` → `postgresql+psycopg://` when wired), ephemeral-disk
  limitation (S3)
- **M5**: `mobile/` Expo app (dir not created yet)
- Minor: `GET /api/v1/items/{id}` is readable by any active client (documented M1
  simplification → per-delivery access control later); worker graceful shutdown flag
  exists but SIGKILL after grace period not configured in compose
- Dev deps (pytest/ruff) are in the image so tests run in-container — acceptable for the
  demo, split into a dev target before production
