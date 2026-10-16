# syntax=docker/dockerfile:1
# Single image for api + worker + migrate (different commands, same code).
# ffmpeg / Tesseract (eng + nep) are baked in — no host installs required.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Media tooling: ffmpeg (audio/video), Tesseract OCR with Nepali language data.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-nep \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer — cached unless pyproject/uv.lock change.
# Dev group (pytest, httpx, ruff) is included so tests can run inside the
# container with `docker compose exec api pytest` (documented demo workflow).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests
COPY scripts ./scripts

RUN mkdir -p /data/media \
    && useradd --create-home --uid 1000 newnews \
    && chown -R newnews:newnews /app /data
USER newnews

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
