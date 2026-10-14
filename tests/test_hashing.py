"""Content hashing / normalization."""

from app.pipeline.hashing import content_hash, normalize_text


def test_normalize_collapses_case_and_whitespace():
    assert normalize_text("  Kathmandu\n\t Mayor   says ") == "kathmandu mayor says"


def test_hash_is_case_and_spacing_insensitive():
    a = content_hash("Breaking News", "The mayor  said the\nproject will start soon.")
    b = content_hash("breaking news", "The mayor said the project will start soon.")
    assert a == b


def test_hash_differs_for_different_content():
    a = content_hash("T1", "same body")
    b = content_hash("T1", "different body")
    c = content_hash("T2", "same body")
    assert a != b
    assert a != c


def test_hash_includes_title():
    with_title = content_hash("Title", "body text")
    without_title = content_hash(None, "body text")
    assert without_title != with_title  # title participates in the digest
