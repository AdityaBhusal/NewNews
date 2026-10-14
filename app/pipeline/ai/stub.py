"""Deterministic stub AI provider.

Zero-cost, offline, reproducible — used for development, demos, and CI.
Heuristics are intentionally simple but explainable: every score comes with a
list of human-readable rationale strings that get persisted with the item.
"""

from __future__ import annotations

import re

from app.pipeline.ai.base import (
    STATUS_LIKELY,
    STATUS_UNCERTAIN,
    STATUS_UNLIKELY,
    URGENCY_HIGH,
    URGENCY_NORMAL,
    Classification,
    CredibilityAssessment,
)

# --- Lexicons -----------------------------------------------------------------

CLICKBAIT = (
    "shocking",
    "you won't believe",
    "unbelievable",
    "viral",
    "miracle",
    "secret they",
    "100%",
    "guaranteed",
    "click here",
    "exposed",
    "destroyed",
    "you need to see",
)

SOURCE_MARKERS = (
    "said",
    "according to",
    "reported",
    "officials",
    "ministry",
    "police",
    "statement",
    "reuters",
    "kantipur",
    "ekantipur",
    "nepalpress",
    "setopati",
    "press release",
)

DATE_PATTERNS = (
    re.compile(r"\b(19|20)\d{2}\b"),
    re.compile(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\b",
        re.IGNORECASE,
    ),
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "politics": (
        "government", "minister", "parliament", "election", "party", "politics",
        "constitution", "opposition", "coalition", "vote", "mp ", "chief minister",
        "cabinet", "gaccha", "samiti", "सरकार", "मन्त्री", "चुनाव",
    ),
    "economy": (
        "economy", "inflation", "bank", "market", "gdp", "tax", "remittance",
        "trade", "budget", "nepse", "interest rate", "export", "import", "price",
        "marketed", "industry", "business", "बजेट", "बैंक",
    ),
    "disaster": (
        "earthquake", "flood", "landslide", "avalanche", "fire", "storm",
        "monsoon", "cloudburst", "casualties", "evacuat", "disaster",
        "भूकम्प", "बाढी",
    ),
    "crime": (
        "police", "arrest", "theft", "murder", "robbery", "fraud", "smuggl",
        "kidnap", "court", "charged", "समातियो", "हत्या",
    ),
    "health": (
        "hospital", "disease", "epidemic", "vaccine", "patients", "health ministry",
        "covid", "dengue", "cholera", "outbreak", "स्वास्थ्य", "रोग",
    ),
    "sports": (
        "match", "football", "cricket", "nepal premier", "tournament", "goal",
        "coach", "player", "fifa", "asian cricket", "gold medal", "खेल",
    ),
    "technology": (
        "software", "internet", "cyber", "ai ", "data ", "startup",
        "digital", "telecom", "nepal telecom", "ntc", "smartphone",
        "application", "प्रविधि",
    ),
    "education": (
        "school", "university", "exam", "students", "syllabus", "scholarship",
        "board", "college", "admission", "शिक्षा", "विद्यालय",
    ),
    "environment": (
        "pollution", "forest", "wildlife", "conservation", "climate", "glacier",
        "rhino", "tiger", "national park", "emission", "वातावरण",
    ),
    "entertainment": (
        "film", "movie", "actor", "singer", "music", "concert", "festival",
        "nepali film", "award", "सिनेमा", "गीत",
    ),
    "international": (
        "india", "china", "usa", "united states", "pakistan", "bangladesh",
        "global", "united nations", "border", "diplomatic",
    ),
}

URGENCY_KEYWORDS_HIGH = (
    "breaking", "urgent", "earthquake", "flood", "landslide", "killed", "dead",
    "deaths", "dies", "curfew", "strike", "bandh", "emergency", "alert",
    "evacuat", "missing", "blasts", "shooting",
)

NEPALI_RANGE = re.compile(r"[ऀ-ॿ]")


def _devanagari_ratio(text: str) -> float:
    if not text:
        return 0.0
    devanagari = len(NEPALI_RANGE.findall(text))
    return devanagari / len(text)


class StubProvider:
    """Deterministic, explainable heuristics. Same input -> same output."""

    name = "stub"

    async def assess_credibility(self, text: str) -> CredibilityAssessment:
        rationale: list[str] = []
        score = 0.55
        lowered = text.lower()

        # Length: substantive text is more likely to be real reporting.
        if len(text) >= 200:
            score += 0.15
            rationale.append("substantive length (+0.15)")
        elif len(text) < 50:
            score -= 0.15
            rationale.append("very short text (-0.15)")

        # Concreteness: dates, named locations, source attributions.
        if any(p.search(text) for p in DATE_PATTERNS):
            score += 0.10
            rationale.append("contains a date reference (+0.10)")
        locations = await self.detect_locations(text)
        if locations:
            score += 0.10
            rationale.append(f"names a known location {locations} (+0.10)")
        if any(marker in lowered for marker in SOURCE_MARKERS):
            score += 0.05
            rationale.append("attributes to a source (+0.05)")

        # Clickbait / hype penalties.
        hits = [w for w in CLICKBAIT if w in lowered]
        if hits:
            score -= 0.20
            rationale.append(f"clickbait phrases {hits} (-0.20)")

        # Shouting: excessive ALL-CAPS words (skip short/acronyms).
        words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) > 3]
        if words:
            caps_ratio = sum(1 for w in words if w.isupper()) / len(words)
            if caps_ratio > 0.3:
                score -= 0.15
                rationale.append(f"excessive ALL-CAPS ({caps_ratio:.0%}) (-0.15)")

        # Exclamation density.
        if len(text) > 0 and text.count("!") / max(len(text), 1) > 0.02:
            score -= 0.10
            rationale.append("excessive exclamation marks (-0.10)")

        score = max(0.0, min(1.0, score))

        # Confidence: how sure are we about the score itself?
        confidence = 0.5
        if len(text) >= 150:
            confidence += 0.2
        if len(text) < 50:
            confidence -= 0.25
        if locations or any(p.search(text) for p in DATE_PATTERNS):
            confidence += 0.1
        confidence = max(0.0, min(1.0, confidence))

        if score >= 0.75:
            status = STATUS_LIKELY
        elif score >= 0.45:
            status = STATUS_UNCERTAIN
        else:
            status = STATUS_UNLIKELY

        return CredibilityAssessment(
            score=round(score, 3),
            confidence=round(confidence, 3),
            status=status,
            rationale=rationale,
        )

    async def classify(self, text: str) -> Classification:
        lowered = text.lower()
        topics = [
            topic
            for topic, keywords in TOPIC_KEYWORDS.items()
            if any(keyword in lowered for keyword in keywords)
        ]
        urgency = (
            URGENCY_HIGH
            if any(keyword in lowered for keyword in URGENCY_KEYWORDS_HIGH)
            else URGENCY_NORMAL
        )
        return Classification(topics=topics, urgency=urgency)

    async def summarize(self, text: str, max_chars: int = 240) -> str:
        sentences = re.split(r"(?<=[.!?।])\s+", text.strip())
        summary = ""
        for sentence in sentences:
            candidate = f"{summary} {sentence}".strip()
            if len(candidate) > max_chars and summary:
                break
            summary = candidate
            if len(summary) >= max_chars:
                break
        return summary or text[:max_chars]

    async def detect_locations(self, text: str) -> list[str]:
        lowered = text.lower()
        known = (
            "kathmandu", "pokhara", "lalitpur", "bhaktapur", "biratnagar", "birgunj",
            "nepalgunj", "butwal", "janakpur", "dharan", "dhangadhi", "itahari",
            "hetauda", "banepa", "chitwan", "pokhara", "mustang", "dolakha",
            "sindhupalchok", "gorkha", "bardiya", "kaski", "morang", "sunsari",
            "rupandehi", "kavrepalanchok", "nuwakot", "sindhuli", "mahottari",
            "sarlahi", "dhankuta", "solukhumbu", "langtang", "annapurna",
            "everest", "chitwan", "pashupatinath", "bouddha", "patan",
        )
        return sorted({place for place in known if place in lowered})

    async def translate(self, text: str, source_language: str, target_language: str) -> str:
        raise NotImplementedError("translation ships with the Groq provider (M2)")
