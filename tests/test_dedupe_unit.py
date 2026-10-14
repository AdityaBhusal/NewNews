"""Near-duplicate shingling/Jaccard helpers — offline, no database."""

from app.pipeline.dedupe import jaccard, shingles

ORIGINAL = (
    "Kathmandu, 12 March 2026 — The Kathmandu Metropolitan City on Tuesday announced "
    "a Rs 250 million budget for road expansion across 14 wards. The provincial "
    "government approved the plan, and the Minister for Urban Development said the "
    "construction will begin next month and continue through the monsoon, according "
    "to a press release. Officials said residents of Banepa and Lalitpur should use "
    "alternative routes during the works."
)

# Reworded copy: one figure changed, title rephrased — as a rival outlet would file it.
REWORDED = (
    "Kathmandu, 12 March 2026 — The Kathmandu Metropolitan City on Tuesday announced "
    "a Rs 300 million budget for road expansion across 14 wards. The provincial "
    "government approved the plan, and the Minister for Urban Development said the "
    "construction will begin next month and continue through the monsoon, according "
    "to a press release. Officials said residents of Banepa and Lalitpur should use "
    "alternative routes during the works."
)

UNRELATED = (
    "Pokhara airport handled a record 412 international flights last month, the "
    "airport authority said, attributing the surge to new regional routes."
)


def test_shingles_are_normalized():
    assert shingles("Hello   WORLD") == shingles("hello world")


def test_shingles_short_text_is_single_token():
    assert shingles("one two") == {"one two"}


def test_shingles_empty_text():
    assert shingles("   ") == set()


def test_jaccard_identity_and_disjoint():
    a = shingles(ORIGINAL)
    assert jaccard(a, a) == 1.0
    assert jaccard(a, shingles(UNRELATED)) < 0.1
    assert jaccard(set(), a) == 0.0


def test_reworded_copy_is_above_hard_threshold():
    score = jaccard(shingles(ORIGINAL), shingles(REWORDED))
    assert score >= 0.85, score


def test_unrelated_texts_are_far_below_suspect_threshold():
    score = jaccard(shingles(ORIGINAL), shingles(UNRELATED))
    assert score < 0.6, score
