"""Client matching rules (pure function)."""

from app.pipeline.matching import subscription_matches


def match(**overrides):
    base = dict(
        sub_topics=["politics"],
        sub_locations=[],
        sub_exclude_topics=[],
        sub_min_urgency="normal",
        item_topics=["politics"],
        item_locations=["kathmandu"],
        item_urgency="normal",
    )
    base.update(overrides)
    return subscription_matches(**base)


def test_topic_match():
    assert match()


def test_topic_mismatch():
    assert not match(item_topics=["sports"])


def test_empty_sub_topics_matches_everything():
    assert match(sub_topics=[], item_topics=["sports"])


def test_location_filter():
    assert match(sub_locations=["kathmandu"], item_locations=["kathmandu"])
    assert not match(sub_locations=["kathmandu"], item_locations=["pokhara"])


def test_empty_sub_locations_matches_everywhere():
    assert match(sub_locations=[], item_locations=["dhangadhi"])


def test_exclusions_win_over_topic_match():
    assert not match(sub_exclude_topics=["politics"], item_topics=["politics", "economy"])
    # unrelated exclusion doesn't block
    assert match(sub_exclude_topics=["sports"], item_topics=["politics"])


def test_urgency_gate():
    assert match(sub_min_urgency="normal", item_urgency="high")
    assert not match(sub_min_urgency="high", item_urgency="normal")
    assert match(sub_min_urgency="low", item_urgency="normal")
