"""Provider factory — config decides which implementation runs."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.pipeline.ai.base import AIProvider
from app.pipeline.ai.stub import StubProvider


@lru_cache
def get_provider() -> AIProvider:
    settings = get_settings()
    provider = settings.ai_provider.lower()
    if provider == "stub":
        return StubProvider()
    if provider == "groq":
        # M2: GroqProvider lands here behind the same interface.
        raise NotImplementedError("Groq provider is planned for M2; use AI_PROVIDER=stub for now")
    raise ValueError(f"unknown AI provider: {settings.ai_provider!r} (expected 'stub' or 'groq')")
