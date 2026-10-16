# Deployment — how the Render setup is wired

Status lives in `docs/roadmap.md` (M4). This page records the topology *as configured*,
so the dashboard isn't the only source of truth.

## Topology

| Piece | Value |
|---|---|
| Web service | **NewNews** (`srv-db7qqh3rjlhs73cmjtp0`) → https://newnews-t54x.onrender.com |
| Runtime | Docker — `./Dockerfile`, context `.`, branch `main` |
| Auto-deploy | on push to `main` |
| Start command | `sh scripts/render_start.sh` — API **+ worker in one container** (free tier allows web services only; production splits them — see below) |
| Health check | `/healthz` |
| Region / plan | singapore / free |
| Worker service | **not created** — free plan rejects non-web services (`only web services allowed for plan`); the worker runs beside the API via `render_start.sh` instead |
| Database | Aiven Postgres — URL scheme **`postgresql+psycopg://`** (Aiven hands out `postgres://`; rewrite on entry) |
| Local parity | `docker-compose.yml` mirrors the shape: `migrate` + `api` + `worker` + `db` |

Configured through the **Render API** with an account key (`RENDER_API_KEY`, local gitignored
`.env` only — never committed, revocable anytime). `render.yaml` blueprint sync is
deliberately *not* enabled — the services already exist; syncing would duplicate them.

## Environment variables (names only — values live in Render and local `.env`)

| Key | Purpose |
|---|---|
| `DATABASE_URL` | remote Postgres for app **and** pre-deploy migrations |
| `ADMIN_API_KEY` | admin routes (clients, review) |
| `AI_PROVIDER` | `stub` \| `groq` |
| `GROQ_API_KEY` | live AI (never committed) |
| `MEDIA_ROOT` | `/data/media` — **ephemeral** on the free tier (see below) |

> **Pre-deploy note:** the Render API exposes no pre-deploy field on service update
> (tried — silently ignored), so migrations run **manually from here** before any push
> that changes schema: `DATABASE_URL=<aiven, psycopg scheme> alembic upgrade head`.
> A `render.yaml` with `preDeployCommand` remains the production path (blueprint sync
> deliberately off — the services already exist; syncing would duplicate them).

## Remote end-to-end check

```bash
BASE_URL=https://newnews-t54x.onrender.com ADMIN_API_KEY=... ./scripts/remote_e2e.sh
```

Readiness → client mint → ingest → worker stages → SSE/feed, entirely against the public URL.

## Free-tier trade-offs (accepted for the demo)

- **Ephemeral disk** — media files under `MEDIA_ROOT` vanish on redeploy/restart; extracted
  text already lives in Postgres, so nothing pipeline-critical is lost. S3-compatible object
  storage is the production path.
- **Spin-down** — first request after idle pays a cold start (~30–60 s); a probe hitting
  `/healthz` after deploy is enough to wake it.
