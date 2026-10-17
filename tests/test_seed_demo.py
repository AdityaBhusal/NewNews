"""Seeder pools must never route to review (decision 2026-10-17).

The review queue is for real editorial work — demo data either auto-validates
(processed pool) or stays at `received` (raw pool, never enqueued).
"""

from __future__ import annotations

import random

import pytest

from app.pipeline.ai.stub import StubProvider
from app.pipeline.validation import certainty_label
from app.seed_demo import is_raw, processed_story, raw_story


@pytest.mark.asyncio
async def test_processed_pool_auto_validates() -> None:
    """Every generated wire story clears score ≥ 0.75 AND confidence ≥ 0.4."""
    rng = random.Random(7)
    provider = StubProvider()
    for i in range(50):
        _title, body = processed_story(rng, f"t{i:04d}")
        assessment = await provider.assess_credibility(body)
        assert assessment.score >= 0.75, (i, assessment.score, body)
        assert assessment.confidence >= 0.4, (i, assessment.confidence, body)
        assert certainty_label(assessment.score, assessment.confidence) == "high"


def test_raw_pool_is_index_deterministic() -> None:
    """Pool assignment is stable across re-runs (same index → same pool)."""
    assert [is_raw(i, 0.4) for i in range(10)] == [True, True, False, False, False] * 2
    assert sum(is_raw(i, 0.4) for i in range(100)) == 40
    assert sum(is_raw(i, 0.0) for i in range(100)) == 0
    assert sum(is_raw(i, 1.0) for i in range(100)) == 100


def test_raw_story_is_thin_intake() -> None:
    """Raw stories carry their tag so identical snippets stay distinct."""
    rng = random.Random(11)
    _title, first = raw_story(rng, "s0001")
    _title2, second = raw_story(rng, "s0002")
    assert "s0001" in first and "s0002" in second
    assert first != second
