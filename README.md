# NewNews — AI-Powered News Intelligence Pipeline (Nepal)

> **Status:** Phase 0 complete — plan and architecture decided, implementation not yet started.
> This README captures the step-by-step plan and the architectural decisions made so far.

NewNews is a prototype news-intelligence platform that accepts raw news/media (text, images,
audio, video, documents), extracts and processes its content, assesses credibility, enriches it
with structured metadata, matches it to configured clients, and delivers eligible items through
fast REST APIs and push-based (SSE) notifications. It is being built as a technical assessment
for a startup interview, emphasizing sound engineering, AI integration, reliability, and
practical trade-offs.

---

## 1. Verified environment & facts (Phase 0 findings)

| Item | Finding | Source |
|---|---|---|
| Repository | Greenfield — only an MIT `LICENSE` existed | local inspection |
| Host machine | Ubuntu 24.04, Python 3.13.7, Node 20, .NET 10 SDK; **no Docker installed** (to be installed for build/verification) | local inspection |
| Groq | Has a **free plan** with rate limits (e.g. `whisper-large-v3`: 20 RPM / 2K RPD; `openai/gpt-oss-120b`: 30 RPM / 200K TPM). OpenAI-compatible API at `https://api.groq.com/openai/v1`. Offers Speech-to-Text, OCR/Image Recognition, Structured Outputs | [Groq docs – Overview](https://console.groq.com/docs/overview), [Rate Limits](https://console.groq.com/docs/rate-limits) |
| Render + Docker | Render **fully supports Docker** deploys (builds from Dockerfile via BuildKit); explicitly recommended when OS-level packages (ffmpeg, tesseract) are required. Persistent disks, private networking, pre-deploy commands supported | [render.com/docs/docker](https://render.com/docs/docker) |
| FastAPI | v0.143.0 (Oct 2026), MIT, Python 3.10–3.14, Pydantic v2 | [pypi.org/project/fastapi](https://pypi.org/project/fastapi/) |
| SQLite concurrency | Single-writer; client/server DB recommended under real concurrency | [sqlite.org FAQ #5](https://sqlite.org/faq.html) |
| Hangfire | Maintained (1.8.23, Feb 2026), but official storages are SQL Server/Redis only | [hangfire.io](https://www.hangfire.io/) |

---

## 2. Technology stack (decided)

| Layer | Choice | Why |
|---|---|---|
| Language/runtime | **Python 3.13** (`python:3.13-slim` image) | Richest AI/media ecosystem (openai SDK, pytesseract, ffmpeg); team works cross-stack |
| API framework | **FastAPI 0.143** + Uvicorn | Async, OpenAPI/Swagger out of the box, Pydantic validation, SSE via Starlette |
| Background worker | Same codebase, **separate container process** (`python -m app.worker`) | Logical separation without microservices |
| Job queue | **PostgreSQL table + `FOR UPDATE SKIP LOCKED`** | Postgres is already required; no Redis/RabbitMQ needed at prototype scale |
| Database | **PostgreSQL** — compose service locally; `DATABASE_URL` env var → remote/Render Postgres in deployment | Team has a remote Postgres; JSON columns, `LISTEN/NOTIFY` available for free later |
| ORM / migrations | **SQLAlchemy 2.0 + Alembic** | De-facto Python standard, async support |
| AI provider | **Groq** (OpenAI-compatible SDK) behind a provider interface + **deterministic stub** for offline/dev/tests | Free tier verified; swapping to OpenAI later is a config change; stub keeps CI/demo zero-cost |
| Media processing | **FFmpeg + Tesseract** (`eng`, `nep` language data) installed **inside the container** | No host-level installs required from any developer |
| Media/original storage | Postgres + local volume (`/data/media`); S3-compatible object storage noted as the production path | Render free tier has ephemeral disks — documented limitation |
| Delivery | REST + **Server-Sent Events** (`/events`); DB-polling (≈200 ms) for cross-process notify in M1 | Meets <2s delivery objective; `LISTEN/NOTIFY` upgrade planned in M3 |
| Auth | API keys per client/subscriber (hashed, in DB), `Authorization: Bearer` | Simple, real, demonstrable |
| Local dev | **Docker Compose**: `api` + `worker` + `db`, healthchecks, volumes, `.env` config | `docker compose up --build` is the only prerequisite |
| Deployment | **Render**: Web Service (api) + Background Worker (worker) from the *same image*, different start command | Matches the shared-codebase / separate-process requirement |

### Rejected alternatives (fair summary)

- **C# / ASP.NET Core** — genuinely strong given the team's background; lost on AI/media library
  ecosystem and explicit project direction. (.NET 10 LTS is supported to Nov 2028.)
- **Node / TypeScript** — weaker media/ML tooling for this workload.
- **SQLite** — viable zero-install option, but a remote Postgres is already available and closer
  to production.
- **Redis / RabbitMQ / Celery broker** — extra infrastructure not justified at prototype scale;
  a Postgres-backed queue covers retries and dead-letter semantics.
- **Ollama / local models** — not installed on the host; CPU-bound transcription/OCR would be slow.
- **WebSockets / mobile push (FCM/APNs)** — more capability than needed for one-way news push;
  documented as future work.

---

## 3. Architecture

Modular monolith: one repository, one container image, two processes (API and worker) plus the
database. Stages are separated by clear module boundaries, not network calls.

```
NewNews/
├── Dockerfile              # single image: ffmpeg, tesseract-ocr + eng/nep data, python deps
├── docker-compose.yml      # api + worker + db, volumes, healthchecks
├── .env.example
├── pyproject.toml          # uv-managed
├── app/
│   ├── api/                # FastAPI routers: ingest, news, clients, events (SSE), health
│   ├── worker/             # pipeline runner: polls jobs table, executes stages
│   ├── pipeline/           # extraction, ai (provider iface + groq + stub), validation,
│   │                       #   enrichment, matching, delivery
│   ├── core/               # config, db sessions, logging + correlation IDs, security
│   └── models/             # SQLAlchemy models + Alembic migrations
├── tests/
├── docs/
│   ├── requirements.md     # (planned) scope, FRs, NFRs, acceptance criteria
│   ├── architecture.md     # (planned) modules, data flow, interfaces, boundaries
│   ├── data-model.md       # (planned) entities, state machine, provenance, versioning
│   ├── roadmap.md          # (planned) milestones and status
│   └── decisions/          # (planned) ADR-0001..0006
├── mobile/                 # (M5) Expo / React Native data-collection app
└── README.md
```

### Pipeline flow

```
Ingestion → Extraction/Processing → AI Validation → Classification/Enrichment
          → Persistence/Audit → Client Matching → Delivery (REST + SSE)
```

- Every item carries a **state machine** (e.g. `received → processing → validated → enriched →
  eligible → delivered`, with `duplicate`, `needs_review`, `failed` branches). Failed, uncertain,
  or duplicate items never silently appear as verified news.
- A **correlation ID** follows each item across all stages; structured logs record every stage
  outcome; audit events are persisted.
- **AI outputs are assessments, not proof of truth** — evidence, confidence, validation status,
  and editorial decisions are stored separately.
- **Idempotency:** ingestion dedupes on content hash + source key; pipeline stages are safe to
  retry; failed jobs go to a dead-letter state after bounded retries.

### Latency objective

< 2 s from eligibility to receipt on a connected subscriber. Measured as: *time an item is
marked `eligible` → SSE event received by a subscribed client* (p95). Long-running stages
(transcription, OCR, translation, editorial review) are asynchronous and explicitly excluded
from this budget.

---

## 4. Step-by-step plan (milestones)

### M0 — Documentation & architecture (current phase)
- [x] Inspect repository and environment
- [x] Verify external claims (Groq free tier, Render Docker support, FastAPI versions)
- [x] Decide stack and record rejected alternatives
- [x] Write README with plan and decisions
- [ ] `docs/requirements.md`, `docs/architecture.md`, `docs/data-model.md`, `docs/roadmap.md`
- [ ] ADRs 0001–0006 in `docs/decisions/`
- [ ] `.gitignore`, `.env.example`

### M1 — Runnable vertical slice (first build milestone)
1. Install Docker Engine + Compose plugin on the host; verify `docker compose` works.
2. Scaffold project (`uv`, FastAPI skeleton, SQLAlchemy, Alembic, config via env).
3. `Dockerfile` (installs `ffmpeg`, `tesseract-ocr`, `tesseract-ocr-eng`, `tesseract-ocr-nep`)
   and `docker-compose.yml` (api, worker, db + healthchecks + volumes).
4. Data model + migration: news items, media assets, pipeline jobs, clients, subscriptions,
   audit events.
5. State machine + Postgres-backed job queue (`FOR UPDATE SKIP LOCKED`, retries, dead-letter).
6. Ingestion API (`POST /api/v1/items`, text first) with API-key auth + correlation IDs.
7. Pipeline stages with **stub AI provider** (deterministic heuristics) end-to-end.
8. Client matching (topics, locations, exclusions, urgency) + REST retrieval + SSE delivery.
9. Tests alongside each feature; `pytest` green.
10. Verify containers build and start; exec into container and confirm `ffmpeg -version` and
    `tesseract --list-langs` (including `nep`).

**M1 acceptance criteria**
- `docker compose up --build` brings up healthy `api`, `worker`, `db` with no host installs of
  ffmpeg/tesseract.
- Submit a text news item via Swagger/curl → it flows through all stages → matched client
  receives it via SSE in < 2 s after eligibility.
- Duplicate / low-confidence / failed items are routed to `duplicate` / `needs_review` /
  `failed` — never shown as verified.
- ffmpeg and Tesseract (with Nepali data) verified inside the container.
- `pytest` passes; docs synchronized with implementation.

### M2 — Real AI + media extraction
- Groq integration behind the provider interface: summary/draft, classification, explainable
  credibility score, translation (ne ↔ en).
- PDF text extraction; image OCR (Tesseract); audio/video transcription (Groq Whisper).
- Duplicate/near-duplicate detection (hash + fuzzy similarity).
- Review-queue workflow for uncertain/high-risk items.

### M3 — Hardening & delivery
- Retry/backoff, dead-letter handling, partial-failure semantics.
- Upgrade cross-process notify to Postgres `LISTEN/NOTIFY`.
- Latency measurement harness reporting p50/p95/p99 for the defined metric.
- Health checks, readiness probes, structured logging dashboards.

### M4 — Deployment (Render)
- Render Blueprint: Web Service (api) + Background Worker (worker) from one image.
- Remote/managed Postgres via `DATABASE_URL`; secrets via Render environment variables.
- Documented limitation: free-tier ephemeral disk → media persistence needs a disk or
  S3-compatible object storage (paid tier).

### M5 — Mobile data collection (Expo / React Native)
- `mobile/` Expo Go app: submit news text + camera photo through the public ingestion API.
- Kept thin — all processing lives server-side.

---

## 5. Setup (planned commands — will be validated in M1)

```bash
# 1. Configure environment
cp .env.example .env        # add GROQ_API_KEY when available (optional for M1 stub mode)

# 2. Build and start everything (API + worker + Postgres)
docker compose up --build

# 3. Verify tooling inside the container
docker compose exec api ffmpeg -version
docker compose exec api tesseract --list-langs   # expect: eng, nep

# 4. Open interactive API docs
open http://localhost:8000/docs

# 5. Run tests
docker compose exec api pytest
```

---

## 6. Open decisions / next actions

- [ ] Docker Engine installation on the host (requires sudo) — needed before M1 verification.
- [ ] Provide `GROQ_API_KEY` when ready for M2 (never committed; env var only).
- [ ] Confirm remote Postgres credentials for the M4 deployment (`DATABASE_URL`).
- [ ] Render free-tier constraints (ephemeral disk, spin-down) accepted for the demo.

---

*License: MIT (see `LICENSE`).*
