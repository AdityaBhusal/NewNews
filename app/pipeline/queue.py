"""Postgres-backed job queue: enqueue + claim via FOR UPDATE SKIP LOCKED."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import PipelineJob


def enqueue_job(
    session: AsyncSession,
    item_id: str,
    stage: str,
    *,
    run_at: datetime | None = None,
    payload: dict | None = None,
) -> PipelineJob:
    job = PipelineJob(
        item_id=item_id,
        stage=stage,
        status="pending",
        max_attempts=get_settings().job_max_attempts,
        run_at=run_at or datetime.now(UTC),
        payload=payload or {},
    )
    session.add(job)
    return job


async def claim_job(session: AsyncSession, worker_id: str) -> str | None:
    """Atomically claim the next runnable job. Returns its id, or None.

    SKIP LOCKED lets multiple worker processes race without blocking each other.
    """
    result = await session.execute(
        text(
            """
            UPDATE pipeline_jobs
               SET status = 'running',
                   locked_by = :worker_id,
                   locked_at = now(),
                   attempts = attempts + 1,
                   updated_at = now()
             WHERE id = (
                   SELECT id FROM pipeline_jobs
                    WHERE status = 'pending' AND run_at <= now()
                    ORDER BY run_at, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                 )
            RETURNING id
            """
        ),
        {"worker_id": worker_id},
    )
    row = result.first()
    return row[0] if row else None


async def pending_job_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(text("count(*)")).select_from(PipelineJob).where(PipelineJob.status == "pending")
    )
    return int(result.scalar_one())


async def reschedule_job(
    session: AsyncSession,
    job_id: str,
    *,
    run_at: datetime,
    error: str,
) -> None:
    await session.execute(
        update(PipelineJob)
        .where(PipelineJob.id == job_id)
        .values(status="pending", run_at=run_at, last_error=error, locked_by=None, locked_at=None)
    )
