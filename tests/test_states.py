"""News item state machine."""

import pytest

from app.pipeline.states import (
    TRANSITIONS,
    InvalidTransition,
    ItemStatus,
    can_transition,
    is_terminal,
    transition,
)


class FakeItem:
    def __init__(self, status: str = ItemStatus.RECEIVED.value) -> None:
        self.status = status
        self.eligible_at = None
        self.delivered_at = None


def test_happy_path_transitions():
    item = FakeItem()
    for target in (
        ItemStatus.PROCESSING,
        ItemStatus.VALIDATED,
        ItemStatus.ENRICHED,
        ItemStatus.ELIGIBLE,
        ItemStatus.DELIVERED,
    ):
        transition(item, target)
    assert item.status == "delivered"
    assert item.eligible_at is not None
    assert item.delivered_at is not None


def test_review_branch_is_allowed():
    item = FakeItem(ItemStatus.PROCESSING.value)
    transition(item, ItemStatus.NEEDS_REVIEW)
    assert item.status == "needs_review"
    # ...and a human can send it back into the pipeline
    transition(item, ItemStatus.PROCESSING)


def test_illegal_transition_raises():
    item = FakeItem(ItemStatus.RECEIVED.value)
    with pytest.raises(InvalidTransition):
        transition(item, ItemStatus.DELIVERED)


def test_terminal_states_have_no_exits():
    for status in (ItemStatus.DELIVERED, ItemStatus.DUPLICATE, ItemStatus.FAILED):
        assert TRANSITIONS[status] == frozenset()
        assert is_terminal(status.value)
        item = FakeItem(status.value)
        with pytest.raises(InvalidTransition):
            transition(item, ItemStatus.PROCESSING)


def test_can_transition_handles_junk():
    assert not can_transition("received", "banana")
    assert not can_transition("banana", "received")
    assert can_transition("enriched", "eligible")
