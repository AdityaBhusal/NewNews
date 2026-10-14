"""News items and their media assets."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class NewsItem(Base, TimestampMixin):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("source_key", "content_hash", name="uq_items_source_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)

    # Ingestion identity (idempotency): dedupe on (source_key, content_hash).
    source_key: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    # Content
    title: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str | None] = mapped_column(String(8))

    # State machine
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    is_duplicate_of: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("news_items.id", ondelete="SET NULL"), nullable=True
    )

    # AI assessments (assessments, not proof of truth)
    summary: Mapped[str | None] = mapped_column(Text)
    credibility_score: Mapped[float | None] = mapped_column(nullable=True)
    credibility_confidence: Mapped[float | None] = mapped_column(nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(32))
    validation_rationale: Mapped[str | None] = mapped_column(Text)

    # Enrichment
    topics: Mapped[list] = mapped_column(JSONB, default=list)
    locations: Mapped[list] = mapped_column(JSONB, default=list)
    urgency: Mapped[str] = mapped_column(String(16), default="normal")

    # Timing (for latency measurement: eligible -> delivered)
    eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict)

    media: Mapped[list[MediaAsset]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )

    kind: Mapped[str] = mapped_column(String(16))  # text | image | audio | video | document
    uri: Mapped[str] = mapped_column(Text)  # local path or remote URL
    filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    media_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)

    extraction_status: Mapped[str] = mapped_column(String(16), default="pending")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    item: Mapped[NewsItem] = relationship(back_populates="media")
