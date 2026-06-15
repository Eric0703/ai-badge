"""Session state machine and business logic.

Statuses per DDL:
  idle | capturing | paused | processing | processing_failed |
  needs_review | reviewing | approved |
  publishing | publish_failed | published |
  retracting | retracted | cancelled

Consent is a boolean field consent_granted, checked before capturing.
"""

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deletion_job import DeletionJob
from app.models.session import Session as SessionModel

logger = logging.getLogger("sessions.service")


class SessionStatus(str, Enum):
    IDLE = "idle"
    CAPTURING = "capturing"
    PAUSED = "paused"
    PROCESSING = "processing"
    PROCESSING_FAILED = "processing_failed"
    NEEDS_REVIEW = "needs_review"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    PUBLISHING = "publishing"
    PUBLISH_FAILED = "publish_failed"
    PUBLISHED = "published"
    RETRACTING = "retracting"
    RETRACTED = "retracted"
    CANCELLED = "cancelled"


TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.IDLE: {SessionStatus.CAPTURING, SessionStatus.CANCELLED},
    SessionStatus.CAPTURING: {SessionStatus.PAUSED, SessionStatus.PROCESSING, SessionStatus.CANCELLED},
    SessionStatus.PAUSED: {SessionStatus.CAPTURING, SessionStatus.CANCELLED},
    SessionStatus.PROCESSING: {SessionStatus.NEEDS_REVIEW, SessionStatus.PROCESSING_FAILED},
    SessionStatus.PROCESSING_FAILED: {SessionStatus.PROCESSING},
    SessionStatus.NEEDS_REVIEW: {SessionStatus.REVIEWING},
    SessionStatus.REVIEWING: {SessionStatus.APPROVED},
    SessionStatus.APPROVED: {SessionStatus.PUBLISHING},
    SessionStatus.PUBLISHING: {SessionStatus.PUBLISHED, SessionStatus.PUBLISH_FAILED},
    SessionStatus.PUBLISH_FAILED: {SessionStatus.PUBLISHING},
    SessionStatus.PUBLISHED: {SessionStatus.RETRACTING},
    SessionStatus.RETRACTING: {SessionStatus.RETRACTED},
    SessionStatus.RETRACTED: set(),
    SessionStatus.CANCELLED: set(),
}


TERMINAL_STATES: set[SessionStatus] = {
    SessionStatus.CANCELLED,
    SessionStatus.RETRACTED,
}


def can_transition(
    current: SessionStatus, target: SessionStatus, consent_granted: bool = False
) -> tuple[bool, str]:
    """Check if a status transition is allowed.

    Self-transition to terminal states is rejected (e.g. cancel an already
    cancelled session → 409).  Non-terminal self-transition (e.g. idle→idle)
    is allowed as a no-op.
    """
    if current == target:
        if current in TERMINAL_STATES:
            return False, f"Session already in terminal state {current.value}"
        return True, ""

    if target == SessionStatus.CAPTURING and not consent_granted:
        return False, "Consent not granted"

    allowed = TRANSITIONS.get(current, set())
    if target not in allowed:
        return False, f"Cannot transition from {current.value} to {target.value}"

    return True, ""


async def retract_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str = "",
) -> SessionModel:
    """Retract a published session via Saga + deletion_jobs pattern.

    Soft-deletes the session and creates 3 deletion_jobs for cascade cleanup.
    Session tombstone preserved: id, user_id, device_id, deleted_at, retracted_by, retraction_reason.
    """
    result = await db.execute(
        select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    current = SessionStatus(session.status)
    allowed, reason_msg = can_transition(current, SessionStatus.RETRACTING)
    if not allowed:
        raise ValueError(reason_msg)

    now = datetime.now(timezone.utc)
    session.status = SessionStatus.RETRACTING.value
    session.deleted_at = now
    session.retracted_by = user_id
    session.retraction_reason = reason
    await db.flush()

    deletion_jobs = [
        DeletionJob(resource_type="delete_artifact_rows", resource_id=session.id, session_id=session.id, status="pending", cascade_targets={"description": "Hard-delete all artifacts"}),
        DeletionJob(resource_type="delete_local_audio", resource_id=session.id, session_id=session.id, status="pending", cascade_targets={"audio_key": session.audio_key}),
        DeletionJob(resource_type="delete_feishu_docs", resource_id=session.id, session_id=session.id, status="pending", cascade_targets={"description": "Feishu stub"}),
    ]
    for dj in deletion_jobs:
        db.add(dj)
    await db.flush()

    logger.info(f"Retract saga: session {session_id}, {len(deletion_jobs)} deletion_jobs")
    return session
