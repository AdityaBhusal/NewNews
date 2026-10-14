"""News item state machine.

received -> processing -> validated -> enriched -> eligible -> delivered
             |              |            |
             +-----------> needs_review <-+   (uncertain / unmatched content)
             +-----------> failed            (stage exception or exhausted retries)
ingest ---> duplicate                          (same source_key + content_hash)

Terminal states: delivered, duplicate, failed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from app.models import NewsItem


class ItemStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    VALIDATED = "validated"
    ENRICHED = "enriched"
    ELIGIBLE = "eligible"
    DELIVERED = "delivered"
    DUPLICATE = "duplicate"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


TERMINAL_STATUSES: frozenset[ItemStatus] = frozenset(
    {ItemStatus.DELIVERED, ItemStatus.DUPLICATE, ItemStatus.FAILED}
)

TRANSITIONS: dict[ItemStatus, frozenset[ItemStatus]] = {
    ItemStatus.RECEIVED: frozenset(
        {ItemStatus.PROCESSING, ItemStatus.DUPLICATE, ItemStatus.FAILED}
    ),
    ItemStatus.PROCESSING: frozenset(
        {ItemStatus.VALIDATED, ItemStatus.NEEDS_REVIEW, ItemStatus.FAILED}
    ),
    ItemStatus.VALIDATED: frozenset(
        {ItemStatus.ENRICHED, ItemStatus.NEEDS_REVIEW, ItemStatus.FAILED}
    ),
    ItemStatus.ENRICHED: frozenset(
        {ItemStatus.ELIGIBLE, ItemStatus.NEEDS_REVIEW, ItemStatus.FAILED}
    ),
    ItemStatus.ELIGIBLE: frozenset({ItemStatus.DELIVERED, ItemStatus.FAILED}),
    ItemStatus.NEEDS_REVIEW: frozenset({ItemStatus.PROCESSING, ItemStatus.FAILED}),
    ItemStatus.DELIVERED: frozenset(),
    ItemStatus.DUPLICATE: frozenset(),
    ItemStatus.FAILED: frozenset(),
}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"invalid status transition: {current} -> {target}")
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    try:
        cur = ItemStatus(current)
        tgt = ItemStatus(target)
    except ValueError:
        return False
    return tgt in TRANSITIONS[cur]


def transition(item: NewsItem, target: ItemStatus | str) -> None:
    """Move *item* to *target*, stamping eligibility/delivery timestamps.

    Raises InvalidTransition if the move is not allowed by the state machine.
    """
    target = ItemStatus(target)
    current = ItemStatus(item.status)
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(current.value, target.value)
    item.status = target.value
    now = datetime.now(UTC)
    if target is ItemStatus.ELIGIBLE and item.eligible_at is None:
        item.eligible_at = now
    if target is ItemStatus.DELIVERED and item.delivered_at is None:
        item.delivered_at = now


def is_terminal(status: str) -> bool:
    try:
        return ItemStatus(status) in TERMINAL_STATUSES
    except ValueError:
        return True
