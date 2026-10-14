# Roadmap — NewNews

Milestones from README §4, with current status. Status as of **M1 verification complete**
(stack built, running, and exercised end-to-end on the host).

Legend: `[x]` done · `[~]` in progress / partially done · `[ ]` not started.

---

## M0 — Documentation & architecture — **mostly complete**

- [x] Inspect repository and environment
- [x] Verify external claims (Groq free tier, Render Docker support, FastAPI versions, SQLite concurrency, Hangfire storages)
- [x] Decide stack and record rejected alternatives
- [x] Write README with plan and decisions
- [x] `docs/requirements.md`, `docs/architecture.md`, `docs/data-model.md`, `docs/roadmap.md`
- [x] ADR-0001 … ADR-0006 in `docs/decisions/`
- [x] `.gitignore`, `.env.example`

---

## M1 — Runnable vertical slice — **complete**

### Completed

- [x] **Scaffold**: uv/`pyproject.toml` (Python ≥ 3.13), FastAPI app factory, SQLAlchemy 2.0
  async + `psycopg`, Alembic env reading `DATABASE_URL` from settings, pydantic-settings `.env`
  config, ruff/pytest config
- [x] **Data model**: `news_items`, `media_assets`, `pipeline_jobs`, `clients`, `subscriptions`,
  `deliveries`, `audit_events` (documented in `docs/data-model.md`)
- [x] **State machine + job queue**: `states.py` transitions with `InvalidTransition`;
  `FOR UPDATE SKIP LOCKED` claims, exponential backoff (5 s base), dead-letter after 3 attempts
- [x] **Ingestion API**: `POST /api/v1/items` — API-key auth, content-hash idempotency,
  202/200 duplicate semantics, race handling, correlation IDs, audit `received`
- [x] **Stub pipeline end-to-end**: `extract → validate → enrich → match` with deterministic
  offline AI (credibility score/confidence/status/rationale, topics, locations, urgency,
  summary) and routing to `validated` / `needs_review` / `failed`
- [x] **Matching + delivery**: subscription rules (exclusions, topic/location axes, urgency
  gate), REST retrieval (`GET /api/v1/news` with `since_id`/`ack`, `GET /api/v1/items/{id}`),
  SSE (`GET /api/v1/events`) with `Last-Event-ID` resume, 200 ms poll, 15 s heartbeats
- [x] **Admin client minting**: `POST /api/v1/clients` (admin key, key shown once),
  `GET /api/v1/clients/me`, `python -m app.seed` demo seeder
- [x] **Tests**: 9 test modules; `42 passed` with `TEST_DATABASE_URL` set (37 unit + 5
  integration), offline/CI runs skip the integration tests; coverage includes hashing, states,
  stub AI determinism, matching rules, security, API smoke, audit trail, full happy path;
  runs on the host and inside the container (`docker compose exec api pytest`)
- [x] **Build assets written**: `Dockerfile` (python:3.13-slim + ffmpeg + tesseract with `nep`,
  dev deps included for in-container tests), `docker-compose.yml` (`db`, `migrate`, `api`,
  `worker`, healthchecks, volume; compose DB published on host port 5433 to avoid clashing
  with the local PostgreSQL used for host-side tests)

### Verification (2026-10-14)

- [x] **Docker installed on host**: Docker 29.1.3 + Compose 2.40.3; PostgreSQL 16 installed
  locally for migrations/integration tests (databases `newnews`, `newnews_test`)
- [x] **Alembic initial revision** generated via autogenerate and applied (`alembic upgrade head`,
  7 tables); Compose `migrate` service exits 0 on every `up`
- [x] **Container verification**: `docker compose up --build` → `api`, `worker`, `db` all
  **healthy**; `ffmpeg -version` → 7.1.5; `tesseract --list-langs` → `eng`, `nep`, `osd`
- [x] **Live end-to-end**: seeded client → `POST /api/v1/items` (202) → worker ran all four
  stages → SSE subscriber received the enriched item **117 ms after `eligible_at`** (budget < 2 s)
- [x] **Guardrails live-checked**: duplicate resubmission → `200` + `duplicate: true` (same id);
  missing API key → `401`; low-confidence text → `needs_review` with zero deliveries (test)
- [x] **Full test suite inside the container**: `42 passed`
- [x] **Docs sync pass**: README acceptance wording corrected (duplicates return the existing
  item instead of a `duplicate` status), README §3 tree and §5 setup validated, ADRs written

### Acceptance criteria (README §4)

- [x] `docker compose up --build` brings up healthy `api`, `worker`, `db` with no host installs of ffmpeg/tesseract
- [x] Submit a text news item via Swagger/curl → it flows through all stages → matched client receives it via SSE in < 2 s after eligibility (measured 117 ms)
- [x] Duplicate submissions return the existing item (`200` + `duplicate: true`) without a second pipeline run; low-confidence items go to `needs_review`; stage failures go to `failed` — unverified content is never surfaced as news
- [x] ffmpeg and Tesseract (with Nepali data) verified inside the container
- [x] `pytest` passes; docs synchronized with implementation

---

## M2 — Real AI + media extraction — **in progress**

- [x] Groq integration behind the provider interface (landed 2026-10-14, `AI_PROVIDER=groq`):
  single structured-output (json_schema) call per text + in-process TTL cache (validate→enrich
  = 1 API call), score/confidence/rationale/topics/locations/urgency/summary, ne ↔ en
  translation; live smoke tests auto-skip without a key; verified E2E on a real Nepali article
  (score 0.45 "uncertain" → `needs_review` with a 5-point rationale — human-in-the-loop path)
- [ ] Media extraction: PDF text (pypdf); image OCR (Tesseract, eng+nep); audio/video
  transcription (Groq Whisper) + upload endpoint + storage volume
- [ ] Duplicate/near-duplicate detection (0.85 Jaccard shingles → `duplicate` state +
  `is_duplicate_of`; 0.6–0.85 flagged for review)
- [ ] Review-queue workflow: list/approve/reject `needs_review` items (admin), approve resumes
  pipeline

## M3 — Hardening & delivery

- [ ] Retry/backoff, dead-letter handling, partial-failure semantics (core retry/dead-letter exists in M1; hardening + operator workflow remain)
- [ ] Upgrade cross-process notify from 200 ms polling to Postgres `LISTEN/NOTIFY`
- [ ] Latency measurement harness reporting p50/p95/p99 for the defined metric (`eligible_at` → SSE receipt)
- [ ] Health checks, readiness probes, structured logging dashboards (probes + JSON logs exist in M1; dashboards remain)

## M4 — Deployment (Render)

- [ ] Render Blueprint: Web Service (api) + Background Worker (worker) from one image
- [ ] Remote/managed Postgres via `DATABASE_URL`; secrets via Render environment variables
- [ ] Documented limitation: free-tier ephemeral disk → media persistence needs a disk or S3-compatible object storage (paid tier)

## M5 — Mobile data collection (Expo / React Native)

- [ ] `mobile/` Expo Go app: submit news text + camera photo through the public ingestion API
- [ ] Kept thin — all processing lives server-side
