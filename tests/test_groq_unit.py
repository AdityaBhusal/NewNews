"""Groq provider parsing helpers — offline, no network."""

from app.pipeline.ai.groq import _Analysis, _clamp01, _clean_list


def test_clamp01_bounds():
    assert _clamp01(0.5) == 0.5
    assert _clamp01(-3) == 0.0
    assert _clamp01(9) == 1.0
    assert _clamp01("0.7") == 0.7
    assert _clamp01(None) == 0.0
    assert _clamp01("junk") == 0.0


def test_clean_list_normalizes():
    assert _clean_list(["Politics", " ECONOMY ", ""]) == ["politics", "economy"]
    assert _clean_list("not-a-list") == []
    assert _clean_list(None) == []


def test_analysis_defaults():
    a = _Analysis(score=0.5, confidence=0.5)
    assert a.urgency == "normal"
    assert a.topics == []
