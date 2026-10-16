# Phase 0 — Verified environment & research findings

Research facts gathered before any code was written (moved out of the README, which now
stays focused on what the system *is*). Each claim was verified against the source linked.

| Item | Finding | Source |
|---|---|---|
| Repository | Greenfield — only an MIT `LICENSE` existed | local inspection |
| Host machine | Ubuntu 24.04, Python 3.13.7, Node 20, .NET 10 SDK; Docker Engine + Compose and PostgreSQL 16 installed during M1 (were missing in Phase 0) | local inspection |
| Groq | Has a **free plan** with rate limits (e.g. `whisper-large-v3`: 20 RPM / 2K RPD; `openai/gpt-oss-120b`: 30 RPM / 200K TPM — the 8 K TPM figure observed live in M2). OpenAI-compatible API at `https://api.groq.com/openai/v1`. Offers Speech-to-Text, OCR/Image Recognition, Structured Outputs | [Groq docs – Overview](https://console.groq.com/docs/overview), [Rate Limits](https://console.groq.com/docs/rate-limits) |
| Render + Docker | Render **fully supports Docker** deploys (builds from Dockerfile via BuildKit); explicitly recommended when OS-level packages (ffmpeg, tesseract) are required. Persistent disks, private networking, pre-deploy commands supported | [render.com/docs/docker](https://render.com/docs/docker) |
| FastAPI | v0.143.0 (Oct 2026), MIT, Python 3.10–3.14, Pydantic v2 | [pypi.org/project/fastapi](https://pypi.org/project/fastapi/) |
| SQLite concurrency | Single-writer; client/server DB recommended under real concurrency | [sqlite.org FAQ #5](https://sqlite.org/faq.html) |
| Hangfire | Maintained (1.8.23, Feb 2026), but official storages are SQL Server/Redis only | [hangfire.io](https://www.hangfire.io/) |
