"""Postgres-backed job queue (FOR UPDATE SKIP LOCKED)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PipelineJob(Base, TimestampMixin):
    __tablename__ = "pipeline_jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "run_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )

    stage: Mapped[str] = mapped_column(String(32))  # extract | validate | enrich | match
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending | running | succeeded | dead

    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
