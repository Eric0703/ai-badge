"""Orchestrator service — job creation, transition, and retry logic.

Pipeline: transcribe → summarize → extract_artifact
No publish job in Phase 1A.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.workflow_event import WorkflowEvent

# Job types for Phase 1A
JOB_TYPE_TRANSCRIBE = "transcribe"
JOB_TYPE_SUMMARIZE = "summarize"
JOB_TYPE_EXTRACT_ARTIFACT = "extract_artifact"
JOB_TYPE_PUBLISH = "publish"

# Pipeline: after each job_type completes, what comes next?
# publish is NOT auto-chained — it is triggered manually after review approval.
PIPELINE_NEXT: dict[str, Optional[str]] = {
    JOB_TYPE_TRANSCRIBE: JOB_TYPE_SUMMARIZE,
    JOB_TYPE_SUMMARIZE: JOB_TYPE_EXTRACT_ARTIFACT,
    JOB_TYPE_EXTRACT_ARTIFACT: None,
    JOB_TYPE_PUBLISH: None,
}

# Job statuses
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


async def create_jobs_for_session(
    db: AsyncSession, session_id: uuid.UUID
) -> list[Job]:
    """Create the pipeline of jobs for a session.

    Creates: transcribe → summarize → extract_artifact
    """
    session_id_str = str(session_id)
    jobs = []

    for job_type in [JOB_TYPE_TRANSCRIBE, JOB_TYPE_SUMMARIZE, JOB_TYPE_EXTRACT_ARTIFACT]:
        idempotency_key = f"{session_id_str}:{job_type}"
        job = Job(
            idempotency_key=idempotency_key,
            session_id=session_id,
            job_type=job_type,
            status=STATUS_PENDING,
        )
        db.add(job)
        jobs.append(job)

    await db.flush()

    # Add workflow events for creation
    for job in jobs:
        event = WorkflowEvent(
            job_id=job.id,
            event_type="job_created",
        )
        db.add(event)

    await db.flush()
    return jobs


async def transition_job(
    db: AsyncSession,
    job: Job,
    new_status: str,
    output_payload: Optional[dict] = None,
    error_message: Optional[str] = None,
) -> Job:
    """Transition a job to a new status and log an event.

    On completion, creates the next job in the pipeline if applicable.
    """
    old_status = job.status
    job.status = new_status

    now = datetime.now(timezone.utc)

    if new_status == STATUS_RUNNING:
        job.started_at = now
    elif new_status == STATUS_COMPLETED:
        job.completed_at = now
        if output_payload is not None:
            job.output_payload = output_payload
    elif new_status == STATUS_FAILED:
        if error_message is not None:
            job.error_message = error_message
        # Set retry schedule
        if job.retry_count < job.max_retries:
            job.next_run_at = now
            job.retry_count += 1
        else:
            job.next_run_at = None

    # Log event
    event = WorkflowEvent(
        job_id=job.id,
        event_type=f"status_{old_status}_to_{new_status}",
    )
    db.add(event)

    await db.flush()

    # If completed, check pipeline and create next job
    if new_status == STATUS_COMPLETED:
        next_job_type = PIPELINE_NEXT.get(job.job_type)
        if next_job_type:
            await _ensure_next_job(db, job.session_id, next_job_type)

    return job


async def retry_job(db: AsyncSession, job: Job) -> Job:
    """Mark a failed job for retry (reset to pending)."""
    return await transition_job(db, job, STATUS_PENDING)


async def _ensure_next_job(
    db: AsyncSession, session_id: uuid.UUID, next_job_type: str
) -> Optional[Job]:
    """Ensure the next pipeline job exists (idempotent)."""
    session_id_str = str(session_id)
    idempotency_key = f"{session_id_str}:{next_job_type}"

    result = await db.execute(
        select(Job).where(Job.idempotency_key == idempotency_key)
    )
    existing = result.scalar_one_or_none()

    if existing is None:
        job = Job(
            idempotency_key=idempotency_key,
            session_id=session_id,
            job_type=next_job_type,
            status=STATUS_PENDING,
        )
        db.add(job)
        await db.flush()

        event = WorkflowEvent(job_id=job.id, event_type="job_created")
        db.add(event)
        await db.flush()
        return job

    return existing
