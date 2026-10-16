# Requirements — NewNews

Scope and requirements for the **M1 vertical slice**. This document is synchronized with the
implementation in `app/` (endpoints, thresholds, and status names below match the code and
`app/core/config.py`). Ambition beyond M1 is listed in §5 and in `docs/roadmap.md`.

## 1. Scope

NewNews ingests raw news items (text first; media since M2 — FR-15), processes them through a staged
pipeline, assesses credibility with an AI provider, enriches them with structured metadata,
matches them against configured client subscriptions, and pushes eligible items to clients over
REST and Server-Sent Events. Every item carries a correlation ID, a state machine status, and a
persistent audit trail. AI outputs are **assessments, not proof of truth**.

In M1 the pipeline runs against a **deterministic offline stub provider**, inside Docker Compose
(`db`, `migrate`, `api`, `worker`), with API-key authentication and an admin endpoint for
minting keys.

## 2. Functional requirements

| ID | Requirement | Notes (as implemented) |
|---|---|---|
| FR-01 | **Idempotent ingestion with API-key auth** | `POST /api/v1/items` requires a client key (`Authorization: Bearer …` or `X-API-Key`; else 401). Payload: `title?`, `body`, `source_key`, `source?`, `language?`, `media[]`. Content hash = SHA-256 over normalized (lowercased, whitespace-collapsed) title+body. New item → **202** with `duplicate: false`; identical `(source_key, content_hash)` → **200** with `duplicate: true` and the existing id. A concurrent-duplicate race is resolved via the unique constraint + `IntegrityError` fallback. |
| FR-02 | **Item state machine** | Ten states (`received, processing, validated, enriched, eligible, delivered, duplicate, needs_review, rejected, failed`); transitions validated in `app/pipeline/states.py` (illegal move raises `InvalidTransition`). Entering `eligible` / `delivered` stamps `eligible_at` / `delivered_at`. Terminal: `delivered`, `duplicate`, `rejected`, `failed`. Editorial decisions (M2): `needs_review` → `validated` (approve) / `rejected` (reject). |
| FR-03 | **Text extraction (M1 text path)** | Whitespace normalization; script-based language detection (≥ 30 % Devanagari → `ne`, else `en`) when not supplied; empty body → item `failed` with audit event `extraction_failed` (job still succeeds — no crash). Media extraction (PDF/OCR/transcription) is the separate `extract_media` first stage — FR-15. |
| FR-04 | **Stub AI credibility assessment with rationale** | `assess_credibility` returns score (0–1), confidence (0–1), status label (`likely_credible` / `uncertain` / `unlikely_credible`) and a list of human-readable rationale strings, all persisted on the item. Routing: score ≥ `CREDIBILITY_VERIFIED_THRESHOLD` (**0.75**) **and** confidence ≥ `MIN_ROUTING_CONFIDENCE` (**0.4**, hardcoded) → `validated`, else `needs_review`. Items in `needs_review` never receive delivery rows. |
| FR-05 | **Enrichment: topics, locations, urgency, summary** | `classify` → `topics` (JSONB) + `urgency` (`low`/`normal`/`high`), `detect_locations` → `locations` (JSONB), `summarize` → `summary`. No topics **and** no locations → `needs_review` (nothing to match against), else `enriched`. |
| FR-06 | **Client matching rules** | For each active subscription of an active client: excluded topics win (any intersection → no match); empty `topics` / `locations` on the subscription = match-everything on that axis; item urgency rank must be ≥ `min_urgency` (`low=0 < normal=1 < high=2`). Each match creates one `deliveries` row; re-running the stage does not double-create rows. An item with zero matches still becomes `eligible` (documented in tests). |
| FR-07 | **REST retrieval** | `GET /api/v1/news` returns the authenticated client's deliveries newest-first (`limit` 1–200 default 50, `since_id` cursor). Read-only by default; `ack=true` marks returned `pending` deliveries `sent` (channel `rest`) and moves an `eligible` item to `delivered`. `GET /api/v1/items/{item_id}` returns item detail (M1: any active authenticated client may read any item). |
| FR-08 | **SSE push with `Last-Event-ID` resume** | `GET /api/v1/events` streams `text/event-stream`; polls the DB every **200 ms** (`SSE_POLL_INTERVAL_MS`) for `pending` deliveries with `id > cursor`, ordered by id. Each event: `id: <delivery_id>`, `event: news`, JSON data. Resume via `Last-Event-ID` header or `last_event_id` query param. On send: delivery → `sent` (channel `sse`), item `eligible` → `delivered`, audit `delivered` with `latency_ms`. `: keepalive` heartbeat every **15 s**. |
| FR-09 | **Admin client minting** | `POST /api/v1/clients` requires the admin key (`ADMIN_API_KEY`, else 403) and creates a client plus 0–10 subscriptions. Response includes the API key **once** (`nn_<8-hex>_<secret>`); only `api_key_prefix` (unique) and SHA-256 `api_key_hash` are stored. `GET /api/v1/clients/me` returns the current client + subscriptions. |
| FR-10 | **Audit trail** | Every stage outcome writes an `audit_events` row (`received`, `extracted`, `dedupe_passed`, `validated`, `needs_review`, `enriched`, `eligible`, `delivered`, `extraction_failed`, `job_dead`; M2 adds `near_duplicate`, `near_duplicate_suspect`, `review_approved`, `review_rejected`) with the stage, event type, JSON detail, and the item's `correlation_id`. |
| FR-11 | **Retry / backoff / dead-letter** | Workers claim jobs atomically (`FOR UPDATE SKIP LOCKED`). On stage exception: retry scheduled at `now + JOB_RETRY_BASE_SECONDS (5) · 2^(attempts−1)` (5 s, 10 s, …), `last_error` stored. After **`JOB_MAX_ATTEMPTS = 3`** attempts the job becomes `dead` and the item transitions to `failed` (audit `job_dead`). |
| FR-12 | **Health probes** | `GET /healthz` (liveness) and `GET /readyz` (readiness: `SELECT 1`, 503 on failure) are unauthenticated; used by Compose/Docker healthchecks. |
| FR-13 | **Near-duplicate detection (M2)** | Stage `dedupe` runs between `extract` and `validate`: token 3-gram shingle sets + Jaccard over recent items (`NEARDUP_*` settings: window 90 d, candidates ≤ 2000, suspect 0.6, hard 0.85). Score ≥ 0.85 → `processing` → `duplicate` with `is_duplicate_of` linked to the canonical item + audit `near_duplicate`; 0.6–0.85 → audit `near_duplicate_suspect`, pipeline continues. Score = max(body-only, title+body) similarity so reworded headlines don't hide matching copy. |
| FR-14 | **Editorial review queue (M2)** | Admin-only (`require_admin`): `GET /api/v1/review` lists `needs_review` items; `GET /api/v1/review/{id}` returns the item + full audit timeline; `POST …/approve` (`note?`) → `needs_review` → `validated` and the pipeline resumes at **enrich** (re-scoring would not change; the editor's verdict *is* validation); `POST …/reject` (`reason` required) → terminal `rejected`. Every decision is audited; wrong state → 409; non-admin → 403. |
| FR-15 | **Media upload & extraction (M2)** | `POST /api/v1/items/{id}/media` (multipart file, client-key auth): accepted only while the item is `received` (else 409), ≤ `MEDIA_MAX_BYTES` (413), recognised MIME/extension else 415; stored under `MEDIA_ROOT/{item_id}/` with a `media_assets` row (`extraction_status=pending`, audit `media_attached`). `extract_media` is the pipeline's **FIRST_STAGE** (pass-through when nothing is attached): images → Tesseract OCR (`nep+eng`), PDFs → pypdf text layer with OCR fallback when the layer is missing *or* is custom-font mojibake (code-punctuation density > 3 % — Preeti/Krutidev-style fonts), audio/video → Groq Whisper (ffmpeg pulls audio from video first). Extracted text is stored on the asset and appended once to the item body under a `[filename — extracted text]` marker so dedupe and the AI assessment see it; per-asset failure sets `extraction_status=error` and the item continues without it. |

## 3. Non-functional requirements

| ID | Requirement | Notes |
|---|---|---|
| NFR-01 | **Delivery latency < 2 s p95** | Measured as *time an item is marked `eligible` → SSE event received by a connected subscribed client*. Long-running stages (transcription, OCR, translation, editorial review) are explicitly excluded. The SSE handler records `latency_ms` per delivery in logs and audit detail. |
| NFR-02 | **Offline / deterministic AI** | Default `AI_PROVIDER=stub`: same input → same output, no network, no API key — dev, demo, and CI run at zero cost. `AI_PROVIDER=groq` selects the real provider (landed M2 W1, behind the same interface). |
| NFR-03 | **Idempotency** | Ingestion dedupes on `(source_key, content_hash)`; every pipeline stage is safe to re-run; matching is guarded by `unique (item_id, client_id)`; duplicate ingestion never re-enqueues work. |
| NFR-04 | **No host-level ffmpeg / tesseract installs** | Both, plus `eng` + `nep` Tesseract language data, are installed **inside the container image**. The only developer prerequisite is Docker. |
| NFR-05 | **Structured JSON logs with correlation IDs** | One JSON object per line (`ts`, `level`, `logger`, `msg`, `correlation_id`, plus whitelisted extras such as `stage`, `item_id`, `job_id`, `duration_ms`, `latency_ms`). A correlation ID is taken from `X-Correlation-ID` or generated per request, echoed in the response header, stored on the item, and copied into every audit event. |
| NFR-06 | **Multi-process safety** | `api` and `worker` are separate processes (and may be multiple containers) sharing one database: job claims use `FOR UPDATE SKIP LOCKED` so no job runs twice; ingestion races are resolved by the unique constraint. |

## 4. M1 acceptance criteria

Adapted from the original M1 plan (now tracked in `docs/roadmap.md`) — all verified 2026-10-14:

- [x] `docker compose up --build` brings up healthy `api`, `worker`, `db` with no host installs of ffmpeg/tesseract.
- [x] Submit a text news item via Swagger/curl → it flows through all stages → matched client receives it via SSE in < 2 s after eligibility.
- [x] Duplicate submissions return the existing item (`200` + `duplicate: true`) without a second pipeline run; low-confidence items go to `needs_review`; stage failures go to `failed` — unverified content is never surfaced as news.
- [x] ffmpeg and Tesseract (with Nepali data) verified inside the container.
- [x] `pytest` passes; docs synchronized with implementation.

Verification evidence: all four compose services healthy; `ffmpeg 7.1.5`, `tesseract --list-langs`
→ `eng`, `nep`; live end-to-end run measured **117 ms** from `eligible_at` to the SSE frame on a
connected subscriber; duplicate resubmission returned `200`/`duplicate: true` with the original id;
missing key → `401`; `42 passed` (37 unit + 5 integration) on the host **and** inside the container.

Note on criterion 3: low-confidence and failed items are routed to `needs_review` / `failed` by
the pipeline; duplicate *resubmissions* are answered at the API with `duplicate: true` and the
existing item (no new row is created), rather than by moving a row into a `duplicate` status —
see `docs/data-model.md` §8.

## 5. Out of scope for M1

| Not in M1 | Target |
|---|---|
| Real Groq provider (summaries, classification, translation ne ↔ en, Whisper transcription) | M2 — ✅ complete 2026-10-15 (text path 10-14; Whisper via `transcribe()` wired to `extract_media`) |
| Media extraction: PDF text, image OCR (Tesseract), audio/video transcription; media stored on a `/data/media` volume | M2 — ✅ landed 2026-10-15 (FR-15; Render free tier disk is ephemeral → M4 object storage) |
| Near-duplicate detection (fuzzy similarity beyond exact content hash); review-queue workflow for `needs_review` items | M2 — ✅ both landed 2026-10-15 |
| Postgres `LISTEN/NOTIFY` cross-process notify (M1 uses 200 ms polling); retry/backoff tuning and latency measurement harness (p50/p95/p99) | M3 |
| Deployment (Render Blueprint, remote Postgres, secrets); S3-compatible object storage | M4 |
| Mobile data-collection app (`mobile/`, Expo / React Native) | M5 |
| WebSockets, mobile push (FCM/APNs), microservices split, per-delivery access control (`GET /api/v1/items/{id}` is client-wide in M1) | Future / not planned |
