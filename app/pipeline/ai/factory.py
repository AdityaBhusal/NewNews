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
        if not settings.groq_api_key:
            raise ValueError("AI_PROVIDER=groq requires GROQ_API_KEY to be set")
        from app.pipeline.ai.groq import GroqProvider

        return GroqProvider(settings.groq_api_key, model=settings.groq_model)
    raise ValueError(f"unknown AI provider: {settings.ai_provider!r} (expected 'stub' or 'groq')")
