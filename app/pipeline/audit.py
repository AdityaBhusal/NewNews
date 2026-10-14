"""Audit trail helper — every stage outcome is persisted."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, NewsItem


async def record_audit(
    session: AsyncSession,
    item: NewsItem,
    *,
    stage: str | None,
    event_type: str,
    detail: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            correlation_id=item.correlation_id,
            item_id=item.id,
            stage=stage,
            event_type=event_type,
            detail=detail or {},
        )
    )
