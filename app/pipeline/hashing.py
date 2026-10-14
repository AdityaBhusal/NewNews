"""Content hashing for ingestion idempotency / deduplication."""

from __future__ import annotations

import hashlib
import re

_WHITESPACE = re.compile(r"\s+")

NORMALIZATION_FLAGS = re.IGNORECASE | re.UNICODE


def normalize_text(text: str) -> str:
    """Collapse all whitespace, trim, and lowercase — case/spacing-insensitive dedupe."""
    return _WHITESPACE.sub(" ", text).strip().lower()


def content_hash(title: str | None, body: str) -> str:
    """SHA-256 over the normalized title+body."""
    parts = [normalize_text(title or ""), normalize_text(body)]
    payload = "\n".join(part for part in parts if part)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
