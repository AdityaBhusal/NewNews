# Data model — NewNews

Source of truth: `app/models/`. All tables are created by Alembic migrations (in M1 the model
classes are authoritative; `alembic/versions/` is populated by autogenerate — see
`docs/roadmap.md`).

## 0. Conventions

- **IDs** are UUID strings (`String(36)`) generated app-side, except `deliveries.id`.
- **Timestamps** are `TIMESTAMPTZ` (`DateTime(timezone=True)`) with `server_default now()`;
  tables with `TimestampMixin` also carry `updated_at` (auto-updated on write). `audit_events`
  has `created_at` only.
- **Status columns are `VARCHAR` with app-level validation**, not Postgres `ENUM` types.
  Deliberate M1 tradeoff: simpler migrations and additive status changes without DDL, at the
  cost of no DB-level enum enforcement (the state machine in `app/pipeline/states.py` and
  Pydantic patterns provide the validation instead).
- **JSONB** is used for list/dict fields (topics, locations, payloads, audit detail).
- **AI fields are assessments, not proof of truth**: scores, confidence, status labels, and
  rationale are the provider's opinion plus its evidence; they never assert that a claim is
  verified fact.

## 1. `news_items` — the pipeline's aggregate root

Unique constraint `uq_items_source_hash (source_key, content_hash)` — the idempotency key.

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID string |
| `correlation_id` | `VARCHAR(36)`, indexed | Set at ingestion; copied to every audit event |
| `source_key` | `VARCHAR(128)` | Stable caller-supplied id (article URL, author+guid); part of dedupe key |
| `content_hash` | `VARCHAR(64)`, indexed | SHA-256 of normalized title+body; part of dedupe key |
| `title` | `VARCHAR(500)`, nullable | |
| `body` | `TEXT` | Normalized by the `extract` stage |
| `source` | `VARCHAR(200)`, nullable | Free-text origin |
| `language` | `VARCHAR(8)`, nullable | `en` / `ne`; detected if not supplied |
| `status` | `VARCHAR(32)`, indexed | State machine, default `received` (§7) |
| `is_duplicate_of` | `VARCHAR(36)`, FK → `news_items.id` `ON DELETE SET NULL`, nullable | Reserved for explicit duplicate linkage (M2 fuzzy matching) |
| `summary` | `TEXT`, nullable | AI assessment output |
| `credibility_score` | `FLOAT`, nullable | 0–1 assessment |
| `credibility_confidence` | `FLOAT`, nullable | 0–1, provider's confidence in *its own* score |
| `validation_status` | `VARCHAR(32)`, nullable | `likely_credible` / `uncertain` / `unlikely_credible` |
| `validation_rationale` | `TEXT`, nullable | Newline-joined rationale strings |
| `topics` | `JSONB`, default `[]` | Enrichment |
| `locations` | `JSONB`, default `[]` | Enrichment (normalized lowercase place names) |
| `urgency` | `VARCHAR(16)`, default `normal` | `low` / `normal` / `high` |
| `eligible_at` | `TIMESTAMPTZ`, nullable | Stamped on entering `eligible` — latency metric start |
| `delivered_at` | `TIMESTAMPTZ`, nullable | Stamped on entering `delivered` |
| `raw_payload` | `JSONB`, default `{}` | Original submission, verbatim |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | `TimestampMixin` |

Relationship: `media` → `media_assets` (cascade delete).

## 2. `media_assets`

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID string |
| `item_id` | `VARCHAR(36)`, FK → `news_items.id` `ON DELETE CASCADE`, indexed | |
| `kind` | `VARCHAR(16)` | `text` \| `image` \| `audio` \| `video` \| `document` (enforced by the request schema) |
| `uri` | `TEXT` | Local path or remote URL |
| `filename` | `VARCHAR(255)`, nullable | |
| `mime_type` | `VARCHAR(100)`, nullable | |
| `size_bytes` | `INTEGER`, nullable | ≥ 0 |
| `media_metadata` | `JSONB`, default `{}` | |
| `extraction_status` | `VARCHAR(16)`, default `pending` | Populated by M2 extraction stages |
| `extracted_text` | `TEXT`, nullable | Populated by M2 |
| `error` | `TEXT`, nullable | Populated by M2 |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

In M1 assets are registered at ingestion but never processed (text-only pipeline).

## 3. `pipeline_jobs` — the Postgres job queue

Index `ix_jobs_claim (status, run_at)` supports the claim query; `item_id` is indexed.

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID string |
| `item_id` | `VARCHAR(36)`, FK → `news_items.id` `ON DELETE CASCADE`, indexed | |
| `stage` | `VARCHAR(32)` | `extract` \| `validate` \| `enrich` \| `match` |
| `status` | `VARCHAR(16)`, indexed | `pending` \| `running` \| `succeeded` \| `dead` |
| `attempts` | `INTEGER`, default 0 | Incremented **at claim time** |
| `max_attempts` | `INTEGER`, default 3 | Equals `JOB_MAX_ATTEMPTS`; exceeded → `dead` |
| `run_at` | `TIMESTAMPTZ`, `server_default now()`, not null | Eligibility time; backoff pushes it forward |
| `locked_by` | `VARCHAR(120)`, nullable | `hostname:pid` of the claiming worker |
| `locked_at` | `TIMESTAMPTZ`, nullable | |
| `last_error` | `TEXT`, nullable | `ExceptionType: message`, truncated to 4000 chars |
| `payload` | `JSONB`, default `{}` | Stage-specific arguments (unused in M1) |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | `TimestampMixin` |

Status lifecycle: `pending → running → succeeded` (or `running → pending` on retry with
`run_at` delayed 5 s · 2^(attempts−1), or `running → dead` after 3 attempts). There is no
automatic `dead → pending`; manual re-queue is an SQL operation.

## 4. `clients`

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID string |
| `name` | `VARCHAR(120)` | |
| `api_key_prefix` | `VARCHAR(16)`, **unique**, indexed | 8-hex lookup prefix from `nn_<prefix>_<secret>`; lets auth find the row without scanning |
| `api_key_hash` | `VARCHAR(64)`, indexed | SHA-256 of the full key — **the full key is shown once at mint and never stored** |
| `is_active` | `BOOLEAN`, default true | `false` → 403 on every request |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

Verification: presented key → extract prefix → load row → `hmac.compare_digest(sha256(key),
api_key_hash)`.

## 5. `subscriptions`

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID string |
| `client_id` | `VARCHAR(36)`, FK → `clients.id` `ON DELETE CASCADE`, indexed | |
| `topics` | `JSONB`, default `[]` | **Empty = match every topic** (this axis is ignored) |
| `locations` | `JSONB`, default `[]` | **Empty = match every location** |
| `exclude_topics` | `JSONB`, default `[]` | Any intersection with item topics → no match (**exclusions win**) |
| `min_urgency` | `VARCHAR(16)`, default `normal` | Gate: item urgency rank (`low=0, normal=1, high=2`) must be ≥ this |
| `is_active` | `BOOLEAN`, default true | Inactive subscriptions are skipped by `match` |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

Matching additionally requires the parent `clients.is_active = true`. Semantics of the rule are
in `app/pipeline/matching.py::subscription_matches` and unit-tested in isolation.

## 6. `deliveries`

Unique constraint `uq_delivery_item_client (item_id, client_id)` — one row per pair, which makes
stage retries idempotent.

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGINT` identity PK, autoincrement | **Doubles as the SSE event id** (`id:` field) and the REST `since_id` cursor; monotonic |
| `item_id` | `VARCHAR(36)`, FK → `news_items.id` `ON DELETE CASCADE`, indexed | |
| `client_id` | `VARCHAR(36)`, FK → `clients.id` `ON DELETE CASCADE`, indexed | |
| `status` | `VARCHAR(16)`, default `pending` | `pending` \| `sent` |
| `channel` | `VARCHAR(16)`, nullable | `sse` \| `rest` |
| `sent_at` | `TIMESTAMPTZ`, nullable | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

`pending → sent` is the whole lifecycle in M1; `pending` rows are what the SSE stream reads, and
`Last-Event-ID` resume is a query for `pending AND id > cursor`.

## 7. `audit_events`

| Column | Type | Notes |
|---|---|---|
| `id` | `VARCHAR(36)` PK | UUID string |
| `correlation_id` | `VARCHAR(36)`, indexed | Copied from the item — joins stages of one submission |
| `item_id` | `VARCHAR(36)`, FK → `news_items.id` `ON DELETE CASCADE`, nullable, indexed | |
| `stage` | `VARCHAR(32)`, nullable | `ingest` \| `extract` \| `validate` \| `enrich` \| `match` \| `deliver` |
| `event_type` | `VARCHAR(64)`, indexed | e.g. `received`, `extracted`, `validated`, `needs_review`, `enriched`, `eligible`, `delivered`, `extraction_failed`, `job_dead` |
| `detail` | `JSONB`, default `{}` | Stage-specific evidence (scores, rationale, matched clients, `latency_ms`, errors) |
| `created_at` | `TIMESTAMPTZ`, indexed, `server_default now()` | No `updated_at` — append-only |

## 8. Item state machine

Authoritative table: `app/pipeline/states.py::TRANSITIONS`.

| From | Allowed transitions | Set by |
|---|---|---|
| `received` | `processing`, `duplicate`, `failed` | `extract` stage; `failed` on empty body / dead job. (`duplicate` is allowed by the table but **never assigned in M1** — see note below) |
| `processing` | `validated`, `needs_review`, `failed` | `validate` stage (`failed` via dead-letter path) |
| `validated` | `enriched`, `needs_review`, `failed` | `enrich` stage |
| `enriched` | `eligible`, `needs_review`, `failed` | `match` stage (`needs_review` when no topics and no locations) |
| `eligible` | `delivered`, `failed` | First SSE send or `GET /api/v1/news?ack=true` |
| `needs_review` | `processing`, `failed` | Manual re-entry (no API/UI in M1) |
| `delivered` | — (terminal) | |
| `duplicate` | — (terminal) | |
| `failed` | — (terminal) | |

Terminal set: `delivered`, `duplicate`, `failed`. Any other target raises `InvalidTransition`.

**Note on `duplicate`:** in M1 deduplication happens *before* an insert — `POST /api/v1/items`
looks up `(source_key, content_hash)` and returns the **existing** row with
`duplicate: true` in the response (200 instead of 202). No new row is created and no row is
moved into the `duplicate` state; the state exists in the machine for future near-duplicate
handling (M2 `is_duplicate_of` linkage).

## 9. ER overview

```
clients ──1:N── subscriptions
   │
   │ 1:N (unique item,client)
   │
news_items ──1:N── media_assets
   │  ├──1:N── pipeline_jobs
   │  ├──1:N── deliveries ──N:1── clients
   │  ├──1:N── audit_events
   │  └──self── is_duplicate_of
```
