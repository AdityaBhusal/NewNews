"""Provider-agnostic AI interface.

Swapping stub -> Groq (or OpenAI later) is a config change (AI_PROVIDER), not a
code change in the pipeline. All outputs are *assessments*, never proof of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Credibility assessment labels (stored on the item, shown to reviewers).
STATUS_LIKELY = "likely_credible"
STATUS_UNCERTAIN = "uncertain"
STATUS_UNLIKELY = "unlikely_credible"

URGENCY_LOW = "low"
URGENCY_NORMAL = "normal"
URGENCY_HIGH = "high"
URGENCY_RANK = {URGENCY_LOW: 0, URGENCY_NORMAL: 1, URGENCY_HIGH: 2}


@dataclass(frozen=True)
class CredibilityAssessment:
    score: float  # 0..1
    confidence: float  # 0..1 — how confident the model is in *its own* score
    status: str  # likely_credible | uncertain | unlikely_credible
    rationale: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Classification:
    topics: list[str] = field(default_factory=list)
    urgency: str = URGENCY_NORMAL


@runtime_checkable
class AIProvider(Protocol):
    name: str

    async def assess_credibility(self, text: str) -> CredibilityAssessment: ...

    async def classify(self, text: str) -> Classification: ...

    async def summarize(self, text: str) -> str: ...

    async def detect_locations(self, text: str) -> list[str]: ...

    async def translate(self, text: str, source_language: str, target_language: str) -> str: ...
