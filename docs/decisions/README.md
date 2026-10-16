# Architecture Decision Records (ADR-0001 … 0007)

Short, dated records of the decisions that shaped the system — context, decision,
consequences. The status of each is *Accepted*.

| ADR | Decision | Why in one line |
|---|---|---|
| [0001](ADR-0001.md) | Python 3.13 + FastAPI over C#/.NET Core and Node/TypeScript | Richest AI/media library ecosystem for this workload |
| [0002](ADR-0002.md) | PostgreSQL over SQLite | Remote Postgres already available; closer to production concurrency |
| [0003](ADR-0003.md) | Postgres-backed job queue over Redis/Celery/RabbitMQ/Hangfire | Retries + dead-letter without another infrastructure component |
| [0004](ADR-0004.md) | Groq behind a provider interface, with a deterministic offline stub | Free tier + zero-cost CI/demo; provider swappable by config |
| [0005](ADR-0005.md) | Modular monolith — one image, two processes (api/worker); Compose locally, Render to deploy | Separation without microservices |
| [0006](ADR-0006.md) | REST + SSE for delivery over WebSockets / mobile push | One-way push at < 2 s needs no socket infra |
| [0007](ADR-0007.md) | Deploy-first ordering; hardening slimmed (defer LISTEN/NOTIFY + latency harness) | Measured latency already 10× under budget; running cloud E2E beats internal polish |

## Rejected alternatives (fair summary)

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
