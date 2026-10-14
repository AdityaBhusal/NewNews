"""Stage registry: dispatch by name, used by the worker."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NewsItem
from app.pipeline import dedupe, enrichment, extraction, matching, validation
from app.pipeline.ai.base import AIProvider

StageHandler = Callable[[AsyncSession, NewsItem, AIProvider], Awaitable[str | None]]

STAGE_HANDLERS: dict[str, StageHandler] = {
    "extract": extraction.run,
    "dedupe": dedupe.run,
    "validate": validation.run,
    "enrich": enrichment.run,
    "match": matching.run,
}

# Ordered pipeline; a handler's return value picks the next stage explicitly,
# this constant is for validation/reporting only.
STAGE_ORDER: tuple[str, ...] = ("extract", "dedupe", "validate", "enrich", "match")

FIRST_STAGE = STAGE_ORDER[0]


def get_handler(stage: str) -> StageHandler:
    try:
        return STAGE_HANDLERS[stage]
    except KeyError:
        raise ValueError(f"unknown pipeline stage: {stage!r}") from None
