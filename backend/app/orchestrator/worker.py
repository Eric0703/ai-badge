"""Worker process — polls jobs table with FOR UPDATE SKIP LOCKED.

Usage: python -m app.orchestrator.worker

Features:
- Polls jobs table every 1s
- FOR UPDATE SKIP LOCKED for concurrency safety
- 30s heartbeat thread updates started_at to prevent timeout
- 120s timeout releases stuck jobs back to pending
- Job type dispatch skeleton (actual handlers in future tickets)
"""

import asyncio
import logging
import os
import signal
import sys
import threading
import time as _time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.models.job import Job

logger = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

# Configuration
POLL_INTERVAL = 1.0  # seconds
HEARTBEAT_INTERVAL = 30  # seconds
JOB_TIMEOUT = 120  # seconds
WORKER_ID = f"worker-{os.getpid()}"

# job_type → handler mapping (skeleton — real handlers in T6/T7)
JOB_HANDLERS: dict[str, callable] = {}

# Shutdown flag
_shutdown = threading.Event()


def register_handler(job_type: str):
    """Decorator to register a job type handler."""
    def decorator(func):
        JOB_HANDLERS[job_type] = func
        return func
    return decorator


async def _release_timed_out_jobs(session: AsyncSession) -> int:
    """Release jobs that have been running too long (no heartbeat)."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=JOB_TIMEOUT)
    result = await session.execute(
        update(Job)
        .where(
            Job.status == "running",
            Job.started_at < cutoff,
        )
        .values(status="pending", started_at=None)
    )
    return result.rowcount


async def _claim_job(session: AsyncSession) -> Job | None:
    """Claim a pending job using FOR UPDATE SKIP LOCKED."""
    result = await session.execute(
        select(Job)
        .where(
            Job.status == "pending",
            (Job.next_run_at == None) | (Job.next_run_at <= datetime.now(timezone.utc)),
        )
        .order_by(Job.priority.desc(), Job.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return result.scalar_one_or_none()


async def _execute_job(session: AsyncSession, job: Job) -> None:
    """Execute a job with heartbeat and timeout handling."""
    # Mark as running
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await session.commit()

    heartbeat_stop = threading.Event()

    def heartbeat_thread():
        """Heartbeat: update started_at every HEARTBEAT_INTERVAL seconds."""
        while not heartbeat_stop.is_set() and not _shutdown.is_set():
            _time.sleep(HEARTBEAT_INTERVAL)
            if not heartbeat_stop.is_set():
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(_send_heartbeat(job.id))
                    loop.close()
                except Exception:
                    pass

    async def _send_heartbeat(job_id):
        async with async_session_factory() as hb_session:
            await hb_session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(started_at=datetime.now(timezone.utc))
            )
            await hb_session.commit()

    # Start heartbeat thread
    t = threading.Thread(target=heartbeat_thread, daemon=True)
    t.start()

    try:
        handler = JOB_HANDLERS.get(job.job_type)
        if handler is None:
            # Unknown job_type — must be marked as failed, never completed
            logger.error(f"[{WORKER_ID}] Unknown job_type={job.job_type}, marking failed")
            async with async_session_factory() as s:
                result = await s.execute(select(Job).where(Job.id == job.id).with_for_update())
                j = result.scalar_one()
                j.status = "failed"
                j.completed_at = datetime.now(timezone.utc)
                j.error_message = f"Unknown job_type: {job.job_type}"
                await s.commit()
        else:
            await handler(session, job)
    except Exception as e:
        logger.error(f"[{WORKER_ID}] Job {job.id} ({job.job_type}) failed: {e}")
        async with async_session_factory() as s:
            result = await s.execute(select(Job).where(Job.id == job.id).with_for_update())
            j = result.scalar_one_or_none()
            if j and j.status == "running":
                j.status = "failed"
                j.error_message = str(e)
                now = datetime.now(timezone.utc)
                if j.retry_count < j.max_retries:
                    j.next_run_at = now
                    j.retry_count += 1
                await s.commit()
    finally:
        heartbeat_stop.set()
        t.join(timeout=1)


async def _process_one(session: AsyncSession) -> bool:
    """Process one job if available. Returns True if a job was processed."""
    # First, release any timed-out jobs
    await _release_timed_out_jobs(session)

    # Try to claim a job
    job = await _claim_job(session)
    if job is None:
        return False

    logger.info(f"[{WORKER_ID}] Claimed job {job.id} type={job.job_type}")
    await _execute_job(session, job)
    return True


async def worker_loop():
    """Main worker loop — polls for jobs indefinitely."""
    # Import agent handlers so they self-register via @register_handler
    import app.agents.capture  # noqa: F401
    import app.agents.distiller  # noqa: F401
    import app.agents.integration  # noqa: F401
    import app.agents.deletion  # noqa: F401

    logger.info(f"[{WORKER_ID}] Starting worker, poll_interval={POLL_INTERVAL}s, heartbeat={HEARTBEAT_INTERVAL}s, timeout={JOB_TIMEOUT}s")
    logger.info(f"[{WORKER_ID}] Registered handlers: {list(JOB_HANDLERS.keys())}")

    if settings.openai_api_key == "sk-placeholder":
        logger.warning(f"[{WORKER_ID}] ⚠️  OPENAI_API_KEY is still 'sk-placeholder' — Whisper/LLM jobs will fail!")
        logger.warning(f"[{WORKER_ID}]    Set OPENAI_API_KEY environment variable or configure an alternative provider.")

    while not _shutdown.is_set():
        try:
            async with async_session_factory() as session:
                processed_job = await _process_one(session)
                processed_del = await _process_deletion(session)
        except Exception as e:
            logger.error(f"[{WORKER_ID}] Error in poll cycle: {e}")

        if not (processed_job or processed_del):
            await asyncio.sleep(POLL_INTERVAL)

    logger.info(f"[{WORKER_ID}] Worker shut down")


async def _process_deletion(session: AsyncSession) -> bool:
    """Claim and process a single deletion_job."""
    from app.models.deletion_job import DeletionJob

    result = await session.execute(
        select(DeletionJob)
        .where(
            DeletionJob.status == "pending",
            (DeletionJob.next_run_at == None) | (DeletionJob.next_run_at <= datetime.now(timezone.utc)),
        )
        .order_by(DeletionJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    deletion_job = result.scalar_one_or_none()
    if deletion_job is None:
        return False

    deletion_job.status = "running"
    deletion_job.started_at = datetime.now(timezone.utc)
    logger.info(f"[{WORKER_ID}] Claimed deletion_job {deletion_job.id} type={deletion_job.resource_type}")

    handler = JOB_HANDLERS.get(deletion_job.resource_type)
    if handler:
        try:
            await handler(session, deletion_job)
        except Exception as e:
            logger.error(f"[{WORKER_ID}] Deletion job {deletion_job.id} failed: {e}")
            deletion_job.status = "failed"
            deletion_job.error_message = str(e)
            await session.commit()
    else:
        # Unknown deletion type — must be marked as failed, never completed
        logger.error(f"[{WORKER_ID}] Unknown deletion type {deletion_job.resource_type}, marking failed")
        deletion_job.status = "failed"
        deletion_job.error_message = f"Unknown deletion_job resource_type: {deletion_job.resource_type}"
        await session.commit()

    return True


def _handle_signal(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"[{WORKER_ID}] Received signal {signum}, shutting down...")
    _shutdown.set()


def main():
    """Entry point for the worker process."""
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        logger.info(f"[{WORKER_ID}] Interrupted, exiting")


if __name__ == "__main__":
    main()
