"""Deterministic stub AI provider."""

import pytest

from app.pipeline.ai.base import STATUS_LIKELY, URGENCY_HIGH
from app.pipeline.ai.stub import StubProvider

FACTUAL = (
    "Kathmandu, 12 March 2026 — The Kathmandu Metropolitan City on Tuesday announced "
    "a Rs 250 million budget for road expansion in 14 wards. Mayor Balen Shah said the "
    "work will begin next month, according to a press release. Officials said the project "
    "will be completed within the fiscal year and asked residents to use alternative routes."
)

SPAM = "SHOCKING!!! You won't believe this miracle secret — click here now! 100% guaranteed!!!"


@pytest.fixture
def provider() -> StubProvider:
    return StubProvider()


async def test_factual_text_scores_high(provider: StubProvider):
    a = await provider.assess_credibility(FACTUAL)
    assert a.score >= 0.75
    assert a.status == STATUS_LIKELY
    assert a.rationale, "assessments must carry an explanation"
    assert 0.0 <= a.confidence <= 1.0


async def test_clickbait_scores_lower_than_factual(provider: StubProvider):
    factual = await provider.assess_credibility(FACTUAL)
    spam = await provider.assess_credibility(SPAM)
    assert spam.score < factual.score
    assert spam.status != STATUS_LIKELY


async def test_stub_is_deterministic(provider: StubProvider):
    first = await provider.assess_credibility(FACTUAL)
    second = await provider.assess_credibility(FACTUAL)
    assert first == second


async def test_classify_topics_and_urgency(provider: StubProvider):
    politics = await provider.classify(
        "The government and opposition party agreed on the election date, ministers said."
    )
    assert "politics" in politics.topics

    disaster = await provider.classify("Earthquake kills 12; flood warning issued for Chitwan")
    assert "disaster" in disaster.topics
    assert disaster.urgency == URGENCY_HIGH


async def test_classify_unknown_text_is_empty_not_hallucinated(provider: StubProvider):
    classification = await provider.classify("The quick brown fox jumps over the lazy dog.")
    assert classification.topics == []
    assert classification.urgency == "normal"


async def test_summarize_respects_limit(provider: StubProvider):
    long_text = " ".join(f"Sentence number {i} about the budget." for i in range(30))
    summary = await provider.summarize(long_text)
    assert 0 < len(summary) <= 260
    assert summary.startswith("Sentence number 0")


async def test_detect_locations(provider: StubProvider):
    found = await provider.detect_locations(
        "Flood damage was reported in Pokhara and Chitwan on Monday."
    )
    assert "pokhara" in found
    assert "chitwan" in found
