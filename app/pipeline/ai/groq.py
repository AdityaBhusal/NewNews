"""Groq provider — real AI behind the same `AIProvider` interface.

Design notes:
- **One structured call per text**: `assess_credibility` / `classify` / `summarize` /
  `detect_locations` all derive from a single JSON-schema-constrained completion, so a
  pipeline run burns ~1 request on the free tier (30 RPM) instead of ~4.
- An in-process TTL cache (keyed by text hash) makes the validate→enrich hand-off free
  within one worker process; a cache miss simply re-calls the API (correct, just slower).
- Outputs are *assessments*, never proof of truth — score/confidence/rationale travel
  together and are persisted by the validation stage.
- Errors propagate to the job queue: retries + dead-letter are the queue's job, not ours.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.logging import get_logger
from app.pipeline.ai.base import (
    STATUS_LIKELY,
    STATUS_UNCERTAIN,
    STATUS_UNLIKELY,
    URGENCY_HIGH,
    URGENCY_LOW,
    URGENCY_NORMAL,
    Classification,
    CredibilityAssessment,
)

log = get_logger("newnews.groq")

DEFAULT_MODEL = "openai/gpt-oss-120b"
CACHE_TTL_S = 600.0
CACHE_MAX_ENTRIES = 256

SYSTEM_PROMPT = (
    "You are a news-intelligence engine for Nepali media. You receive one news text "
    "(English or Nepali) and return a strict JSON assessment. Rules:\n"
    "- score: 0..1 credibility of the *text as journalism* — concrete dates, places, named "
    "sources, attribution raise it; vagueness, hype, clickbait, excessive caps/punctuation "
    "lower it. You assess presentation and evidence, never political truth.\n"
    "- confidence: 0..1 how confident you are in your own score.\n"
    "- rationale: 3-6 short strings citing exactly what in the text drove the score.\n"
    "- topics: 0..5 of [politics, economy, disaster, crime, health, sports, technology, "
    "education, environment, entertainment, international] (lowercase).\n"
    "- locations: lowercase place/city/district names explicitly mentioned.\n"
    "- urgency: high for breaking/ongoing harm (deaths, disaster, strike, curfew, arrest); "
    "low for evergreen/opinion; else normal.\n"
    "- summary: 1-2 sentences, same language as the input.\n"
    "Return JSON only."
)

ANALYSIS_SCHEMA = {
    "name": "news_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "number"},
            "confidence": {"type": "number"},
            "rationale": {"type": "array", "items": {"type": "string"}},
            "topics": {"type": "array", "items": {"type": "string"}},
            "locations": {"type": "array", "items": {"type": "string"}},
            "urgency": {"type": "string", "enum": [URGENCY_LOW, URGENCY_NORMAL, URGENCY_HIGH]},
            "summary": {"type": "string"},
        },
        "required": [
            "score",
            "confidence",
            "rationale",
            "topics",
            "locations",
            "urgency",
            "summary",
        ],
        "additionalProperties": False,
    },
}


def _clamp01(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _clean_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(v).strip().lower() for v in values if str(v).strip()]


@dataclass
class _Analysis:
    score: float
    confidence: float
    rationale: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    urgency: str = URGENCY_NORMAL
    summary: str = ""


class GroqProvider:
    """OpenAI-compatible client pointed at Groq; deterministic parse, clamped ranges."""

    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        stt_model: str = "whisper-large-v3",
        base_url: str = "https://api.groq.com/openai/v1",
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._stt_model = stt_model
        self._cache: dict[str, tuple[float, _Analysis]] = {}

    # --- core: one call, many views --------------------------------------

    async def _analyze(self, text: str) -> _Analysis:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None and now - hit[0] < CACHE_TTL_S:
            return hit[1]

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"TEXT:\n{text[:get_settings().ai_max_input_chars]}"},
            ],
            response_format={"type": "json_schema", "json_schema": ANALYSIS_SCHEMA},
            temperature=0.2,
        )
        raw = response.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Schema mode should prevent this; treat as a provider error → queue retry.
            raise ValueError(f"Groq returned non-JSON content: {raw[:200]!r}") from None

        urgency = str(data.get("urgency", URGENCY_NORMAL)).strip().lower()
        if urgency not in (URGENCY_LOW, URGENCY_NORMAL, URGENCY_HIGH):
            urgency = URGENCY_NORMAL
        analysis = _Analysis(
            score=round(_clamp01(data.get("score")), 3),
            confidence=round(_clamp01(data.get("confidence")), 3),
            rationale=[str(r) for r in (data.get("rationale") or [])][:8],
            topics=_clean_list(data.get("topics"))[:5],
            locations=_clean_list(data.get("locations"))[:12],
            urgency=urgency,
            summary=str(data.get("summary") or "").strip(),
        )

        if len(self._cache) >= CACHE_MAX_ENTRIES:
            self._cache.clear()  # cheap bound; TTL covers the steady state
        self._cache[key] = (now, analysis)
        return analysis

    # --- AIProvider protocol ---------------------------------------------

    async def assess_credibility(self, text: str) -> CredibilityAssessment:
        a = await self._analyze(text)
        # Advisory label with the default bands; the validate stage re-derives routing
        # from configured thresholds (settings), which always wins.
        if a.score >= 0.75:
            status = STATUS_LIKELY
        elif a.score >= 0.45:
            status = STATUS_UNCERTAIN
        else:
            status = STATUS_UNLIKELY
        return CredibilityAssessment(
            score=a.score,
            confidence=a.confidence,
            status=status,
            rationale=a.rationale,
        )

    async def classify(self, text: str) -> Classification:
        a = await self._analyze(text)
        return Classification(topics=a.topics, urgency=a.urgency)

    async def summarize(self, text: str) -> str:
        a = await self._analyze(text)
        return a.summary or re.sub(r"\s+", " ", text).strip()[:240]

    async def detect_locations(self, text: str) -> list[str]:
        a = await self._analyze(text)
        return a.locations

    # --- speech-to-text (W3 media extraction; not part of the AIProvider
    # protocol — media_extract discovers it with `getattr`, so the stub simply
    # has no transcription and reports a clean per-asset error instead).

    async def transcribe(self, path: str) -> str:
        """Groq Whisper transcription of a local audio file (mp3/wav/m4a/...)."""
        with open(path, "rb") as fh:
            response = await self._client.audio.transcriptions.create(
                model=self._stt_model,
                file=fh,
            )
        return (response.text or "").strip()

    async def translate(self, text: str, source_language: str, target_language: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a translation engine. Translate the user's text from "
                        f"{source_language} to {target_language}. Preserve meaning, names and "
                        "numbers. Output ONLY the translation, no quotes or commentary."
                    ),
                },
                {"role": "user", "content": text[: get_settings().ai_max_input_chars]},
            ],
            temperature=0.1,
        )
        return (response.choices[0].message.content or "").strip()
