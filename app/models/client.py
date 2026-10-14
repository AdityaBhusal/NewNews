"""Clients, their subscriptions, and per-client delivery records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    api_key_prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    api_key_hash: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )

    topics: Mapped[list] = mapped_column(JSONB, default=list)
    locations: Mapped[list] = mapped_column(JSONB, default=list)
    exclude_topics: Mapped[list] = mapped_column(JSONB, default=list)
    min_urgency: Mapped[str] = mapped_column(String(16), default="normal")
    is_active: Mapped[bool] = mapped_column(default=True)


class Delivery(Base, TimestampMixin):
    """One row per (item, client). Sequential PK doubles as the SSE event ID."""

    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("item_id", "client_id", name="uq_delivery_item_client"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | sent
    channel: Mapped[str | None] = mapped_column(String(16))  # sse | rest
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
