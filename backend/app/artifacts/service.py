"""Artifact service — unified state change functions.

All artifact & related session status transitions MUST go through this module.
Router/handler code should never directly write artifact.status or session.status.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact
from app.models.session import Session as SessionModel
from app.models.job import Job
from app.models.workflow_event import WorkflowEvent
from app.sessions.service import SessionStatus, can_transition

logger = logging.getLogger("artifacts.service")


async def approve_artifact(
    db: AsyncSession,
    artifact: Artifact,
    reviewer_id: uuid.UUID,
    comment: str = "",
) -> Artifact:
    """Approve an artifact. If all artifacts for the session are approved, advance session.

    Side effects: writes workflow_event, may transition session status.
    """
    artifact.status = "approved"
    artifact.review_status = "approved"
    artifact.review_comment = comment
    artifact.updated_at = datetime.now(timezone.utc)

    # Record workflow event (artifact-level, not job-bound)
    db.add(WorkflowEvent(
        resource_type="artifact",
        resource_id=artifact.id,
        artifact_id=artifact.id,
        session_id=artifact.session_id,
        event_type="artifact_approved",
        event_data=f"reviewer={reviewer_id}",
    ))
    await db.flush()

    # Check if ALL artifacts for this session are approved
    r = await db.execute(
        select(Artifact).where(
            Artifact.session_id == artifact.session_id,
            Artifact.status != "approved",
        )
    )
    remaining = r.scalars().all()
    if not remaining:
        await _transition_session(db, artifact.session_id, SessionStatus.APPROVED)

    logger.info(f"Artifact {artifact.id} approved by {reviewer_id}")
    return artifact


async def reject_artifact(
    db: AsyncSession,
    artifact: Artifact,
    reviewer_id: uuid.UUID,
    comment: str = "",
) -> tuple[Artifact, Job]:
    """Reject an artifact and create a re-distill job.

    IMPORTANT: uses the SAME db session (no async_session_factory).
    Returns (updated_artifact, new_retry_job).
    """
    artifact.status = "rejected"
    artifact.review_status = "rejected"
    artifact.review_comment = comment
    artifact.updated_at = datetime.now(timezone.utc)

    # Record workflow event (artifact-level)
    db.add(WorkflowEvent(
        resource_type="artifact",
        resource_id=artifact.id,
        artifact_id=artifact.id,
        session_id=artifact.session_id,
        event_type="artifact_rejected",
        event_data=f"reviewer={reviewer_id}",
    ))

    # Create retry job in the SAME transaction
    new_job = Job(
        idempotency_key=f"{artifact.session_id}:extract_artifact:retry-{uuid.uuid4().hex[:8]}",
        session_id=artifact.session_id,
        job_type="extract_artifact",
        status="pending",
        input_payload={"retry_reason": comment},
    )
    db.add(new_job)
    await db.flush()

    logger.info(f"Artifact {artifact.id} rejected by {reviewer_id}, created retry job {new_job.id}")
    return artifact, new_job


async def request_publish(
    db: AsyncSession,
    artifact: Artifact,
    user_id: uuid.UUID,
) -> tuple[Artifact, Job]:
    """Create a publish job for an approved artifact. Returns 403 equivalent via ValueError if not approved.

    Uses the SAME db session. Returns (artifact, publish_job).
    """
    if artifact.status != "approved":
        raise ValueError("Only approved artifacts can be published")

    # Create publish job
    publish_job = Job(
        idempotency_key=f"{artifact.session_id}:publish:{artifact.id}",
        session_id=artifact.session_id,
        job_type="publish",
        status="pending",
        input_payload={"artifact_id": str(artifact.id)},
    )
    db.add(publish_job)

    # Transition session to publishing
    await _transition_session(db, artifact.session_id, SessionStatus.PUBLISHING)
    await db.flush()

    logger.info(f"Publish requested for artifact {artifact.id}, job {publish_job.id}")
    return artifact, publish_job


async def mark_published(
    db: AsyncSession,
    artifact: Artifact,
    feishu_doc_id: str = "",
) -> Artifact:
    """Mark an artifact (and its session) as published.

    Called by the publish job handler.
    """
    artifact.status = "published"
    artifact.published_at = datetime.now(timezone.utc)
    await db.flush()

    await _transition_session(db, artifact.session_id, SessionStatus.PUBLISHED)
    logger.info(f"Artifact {artifact.id} published, feishu_doc={feishu_doc_id}")
    return artifact


# ── Internal helpers ─────────────────────────────────────────────────

async def _transition_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    target: SessionStatus,
) -> SessionModel:
    """Transition a session to a target status with state machine validation."""
    r = await db.execute(
        select(SessionModel).where(SessionModel.id == session_id)
    )
    session = r.scalar_one_or_none()
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    current = SessionStatus(session.status)
    allowed, reason = can_transition(current, target)
    if not allowed:
        raise ValueError(f"Cannot transition session {session_id} from {current.value} to {target.value}: {reason}")

    session.status = target.value
    session.updated_at = datetime.now(timezone.utc)

    # Record workflow event (session-level transition)
    db.add(WorkflowEvent(
        resource_type="session",
        resource_id=session_id,
        session_id=session_id,
        event_type=f"session_{target.value}",
        event_data=f"session_id={session_id}",
    ))

    logger.info(f"Session {session_id}: {current.value} → {target.value}")
    return session
