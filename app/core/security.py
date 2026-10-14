"""API key generation and verification (hashed at rest)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

KEY_PREFIX = "nn_"


def hash_key(key: str) -> str:
    """SHA-256 hex digest of the full key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(full_key, prefix, hash)``. The full key is shown once, never stored."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    full_key = f"{KEY_PREFIX}{prefix}_{secret}"
    return full_key, prefix, hash_key(full_key)


def key_prefix(key: str) -> str | None:
    """Extract the lookup prefix from a presented key, or None if malformed."""
    if not key.startswith(KEY_PREFIX):
        return None
    rest = key[len(KEY_PREFIX) :]
    prefix, _, _ = rest.partition("_")
    return prefix or None


def verify_key(presented_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_key(presented_key), stored_hash)
