"""Worker entrypoint: `python -m app.worker`.

Runs in its own container process, shares the codebase (modular monolith),
claims jobs with FOR UPDATE SKIP LOCKED, retries with exponential backoff,
and dead-letters after bounded attempts.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.context import set_correlation_id
from app.core.db import SessionLocal
from app.core.logging import get_logger, setup_logging
from app.models import NewsItem, PipelineJob
from app.pipeline.ai.base import AIProvider
from app.pipeline.ai.factory import get_provider
from app.pipeline.audit import record_audit
from app.pipeline.queue import claim_job, enqueue_job
from app.pipeline.runner import get_handler
from app.pipeline.states import InvalidTransition, ItemStatus, transition

log = get_logger("newnews.worker")

StopEvent = asyncio.Event


async def _handle_failure(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
    exc: BaseException,
) -> None:
    """Retry with exponential backoff, or dead-letter + fail the item."""
    async with session_factory() as session:
        job = await session.get(PipelineJob, job_id)
        if job is None:
            log.error("job disappeared", extra={"job_id": job_id})
            return

        error = f"{type(exc).__name__}: {exc}"
        job.last_error = error[:4000]
        job.locked_by = None
        job.locked_at = None

        settings = get_settings()
        item = await session.get(NewsItem, job.item_id) if job.item_id else None

        if job.attempts >= job.max_attempts:
            job.status = "dead"
            if item is not None:
                try:
                    transition(item, ItemStatus.FAILED)
                except InvalidTransition:
                    pass  # item already terminal — job still dead-letters
                await record_audit(
                    session,
                    item,
                    stage=job.stage,
                    event_type="job_dead",
                    detail={
                        "job_id": job.id,
                        "attempts": job.attempts,
                        "error": error[:1000],
                    },
                )
            log.error(
                "job dead-lettered",
                extra={"job_id": job_id, "stage": job.stage, "attempts": job.attempts},
            )
        else:
            backoff = settings.job_retry_base_seconds * (2 ** max(job.attempts - 1, 0))
            job.status = "pending"
            job.run_at = datetime.now(UTC) + timedelta(seconds=backoff)
            log.warning(
                "job failed, retry scheduled",
                extra={
                    "job_id": job_id,
                    "stage": job.stage,
                    "attempts": job.attempts,
                    "status": "retry",
                },
            )
        await session.commit()


async def process_next(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    provider: AIProvider | None = None,
    worker_id: str = "worker",
) -> bool:
    """Claim and execute one job. Returns True if a job was processed."""
    provider = provider or get_provider()

    async with session_factory() as session:
        job_id = await claim_job(session, worker_id)
        await session.commit()
    if job_id is None:
        return False

    async with session_factory() as session:
        job = await session.get(PipelineJob, job_id)
        if job is None:
            return True
        item = await session.get(NewsItem, job.item_id)
        try:
            if item is None:
                raise ValueError(f"news item {job.item_id} not found for job {job.id}")
            # Every log line and audit row for this job carries the item's id.
            set_correlation_id(item.correlation_id)
            handler = get_handler(job.stage)
            started = asyncio.get_running_loop().time()
            next_stage = await handler(session, item, provider)
            duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
            job.status = "succeeded"
            if next_stage:
                enqueue_job(session, item.id, next_stage)
            log.info(
                "stage completed",
                extra={
                    "stage": job.stage,
                    "job_id": job.id,
                    "item_id": item.id,
                    "duration_ms": duration_ms,
                    "attempts": job.attempts,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — worker must never die on a stage error
            await session.rollback()
            await _handle_failure(session_factory, job_id, exc)
    return True


async def drain(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    provider: AIProvider | None = None,
    worker_id: str = "drainer",
    max_jobs: int = 100,
) -> int:
    """Process jobs until the queue is empty (used by tests and demos)."""
    processed = 0
    while processed < max_jobs:
        if not await process_next(session_factory, provider, worker_id):
            break
        processed += 1
    return processed


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    provider = get_provider()

    stop = StopEvent()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover — non-POSIX
            pass

    log.info(
        "worker started",
        extra={"event": "worker_start", "worker": worker_id},
    )
    while not stop.is_set():
        try:
            processed = await process_next(SessionLocal, provider, worker_id)
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
            processed = False
        if not processed:
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.worker_poll_interval_s
                )
            except TimeoutError:
                pass
    log.info("worker stopped", extra={"event": "worker_stop"})


if __name__ == "__main__":
    asyncio.run(main())
