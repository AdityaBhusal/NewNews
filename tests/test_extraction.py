"""Text extraction helpers."""

from app.pipeline.extraction import detect_language


def test_english_detected():
    assert detect_language("The government announced the budget on Tuesday.") == "en"


def test_nepali_detected():
    assert detect_language("सरकारले आज बजेट पेश गरेको छ।") == "ne"


def test_empty_defaults_to_english():
    assert detect_language("") == "en"
