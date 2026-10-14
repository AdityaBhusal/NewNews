"""Live Groq smoke tests — run only when GROQ_API_KEY is set (skipped offline/CI).

Kept deliberately small (~4 API calls) to stay inside free-tier rate limits.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.groq_api_key, reason="GROQ_API_KEY not set — live Groq tests skipped"
)

# Real content from the user's sample screenshot (OK Nepali, 2026-10-14) — Nepali script.
NEPALI_SAMPLE = (
    "महिलालाई कुटिपट गरेपछि स्वयम्भू प्रहरीको हिरासत पुगेका थिए सांसद सुनार। "
    "महिला हिंसासम्बन्धी अडियो सार्वजनिक भएपछि सर्वसम्मत सांसद घनश्याम सुनार पार्टीले "
    "आन्तरिक छानबिन अघि बढाएको छ। प्रहरीको अनुसार अडियोबारे हालसम्म कुनै उजुरी परेको छैन।"
)

ENGLISH_SAMPLE = (
    "Kathmandu, 14 October 2026 — The cabinet on Tuesday approved Rs 1.2 billion in flood "
    "relief for Chitwan district, the Ministry of Finance said in a statement. According to "
    "the press release, the funds will reach 18,000 households through local municipalities "
    "next week."
)


@pytest.fixture
def provider():
    from app.pipeline.ai.groq import GroqProvider

    return GroqProvider(settings.groq_api_key, model=settings.groq_model)


async def test_english_assessment_is_well_formed(provider):
    a = await provider.assess_credibility(ENGLISH_SAMPLE)
    assert 0.0 <= a.score <= 1.0
    assert 0.0 <= a.confidence <= 1.0
    assert a.rationale, "Groq must return a rationale"
    assert a.status in ("likely_credible", "uncertain", "unlikely_credible")


async def test_nepali_classify_and_locations(provider):
    c = await provider.classify(NEPALI_SAMPLE)
    assert isinstance(c.topics, list)
    assert c.urgency in ("low", "normal", "high")
    locations = await provider.detect_locations(NEPALI_SAMPLE)
    assert isinstance(locations, list)  # place names if the model found any


async def test_translation_ne_to_en(provider):
    out = await provider.translate(NEPALI_SAMPLE.split("।")[0] + "।", "ne", "en")
    assert out
    assert out != NEPALI_SAMPLE  # actually translated, not echoed


async def test_cache_reuses_single_call(provider):
    """assess + summarize on the same text should hit the in-process cache (1 API call)."""
    before = provider._cache.copy()
    await provider.assess_credibility(ENGLISH_SAMPLE)
    calls_after_assess = len(provider._cache) - len(before)
    await provider.classify(ENGLISH_SAMPLE)
    await provider.summarize(ENGLISH_SAMPLE)
    calls_after_all = len(provider._cache) - len(before)
    assert calls_after_assess == 1
    assert calls_after_all == 1  # classify/summarize reused the cached analysis
