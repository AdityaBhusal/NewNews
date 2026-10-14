"""Pydantic request/response schemas for the public API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MediaIn(BaseModel):
    kind: str = Field(pattern="^(text|image|audio|video|document)$")
    uri: str = Field(min_length=1, max_length=2000)
    filename: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    size_bytes: int | None = Field(default=None, ge=0)
    media_metadata: dict = Field(default_factory=dict)


class ItemCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)
    source: str | None = Field(default=None, max_length=200)
    source_key: str = Field(
        min_length=1,
        max_length=128,
        description="Stable id for idempotent submissions (e.g. article URL or author+guid).",
    )
    language: str | None = Field(default=None, max_length=8)
    media: list[MediaIn] = Field(default_factory=list)


class ItemAccepted(BaseModel):
    id: str
    status: str
    correlation_id: str
    duplicate: bool


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    title: str | None
    body: str
    source: str | None
    language: str | None
    summary: str | None
    credibility_score: float | None
    credibility_confidence: float | None
    validation_status: str | None
    validation_rationale: str | None
    topics: list[str]
    locations: list[str]
    urgency: str
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    eligible_at: datetime | None
    delivered_at: datetime | None


class DeliveryOut(BaseModel):
    delivery_id: int
    item: ItemOut


class NewsList(BaseModel):
    count: int
    items: list[DeliveryOut]


class SubscriptionIn(BaseModel):
    topics: list[str] = Field(default_factory=list, max_length=32)
    locations: list[str] = Field(default_factory=list, max_length=32)
    exclude_topics: list[str] = Field(default_factory=list, max_length=32)
    min_urgency: str = Field(default="normal", pattern="^(low|normal|high)$")


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subscriptions: list[SubscriptionIn] = Field(default_factory=list, max_length=10)


class SubscriptionOut(BaseModel):
    id: str
    topics: list[str]
    locations: list[str]
    exclude_topics: list[str]
    min_urgency: str
    is_active: bool


class ClientOut(BaseModel):
    id: str
    name: str
    is_active: bool
    created_at: datetime
    subscriptions: list[SubscriptionOut] = Field(default_factory=list)


class ClientCreated(ClientOut):
    api_key: str = Field(description="Shown once — store it; only the hash is kept.")
