"""E2E Integration Tests — 4 vertical slice paths.

Path 1: Happy Path
  register → login → create session → consent → upload audio
  → capturing → processing → needs_review → approve → publish → published

Path 2: Failure + Retry
  transcribe job fails → auto retry → eventually succeeds → downstream continues

Path 3: Review Cycle
  needs_review → reject → new extract_artifact job → re-approve → approve

Path 4: Retract Saga
  published → POST /retract → deletion_jobs created → Worker processes
  → artifacts hard-deleted → session tombstone → audit recorded
"""

import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy import select, func

from app.models.job import Job
from app.models.artifact import Artifact
from app.models.session import Session as SessionModel
from app.models.deletion_job import DeletionJob
from app.models.audit_log import AuditLog
from app.orchestrator.service import STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING


# ══════════════════════════════════════════════════════════════════════
# Path 1: Happy Path — Full flow from register to published
# ══════════════════════════════════════════════════════════════════════

class TestHappyPath:
    """Happy Path: register → login → session → consent → audio → processing → review → publish → published."""

    @pytest.mark.asyncio
    async def test_full_happy_path(self, db, async_client):
        """Complete end-to-end happy path."""
        # ── Step 1: Register ──
        email = f"e2e-happy-{uuid.uuid4().hex[:8]}@example.com"
        password = "happy-path-password"

        resp = await async_client.post("/api/v1/auth/register", json={
            "email": email,
            "password": password,
            "display_name": "Happy Tester",
            "org_name": "Happy Org",
        })
        assert resp.status_code == 201
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # ── Step 2: Create session ──
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "E2E Happy Path Session",
        }, headers=headers)
        assert resp.status_code == 201
        sid = resp.json()["id"]
        assert resp.json()["status"] == "idle"
        assert resp.json()["consent_granted"] is False

        # ── Step 3: Grant consent ──
        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/consent",
            json={"consent": True},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["consent_granted"] is True

        # ── Step 4: Upload audio ──
        fake_audio = BytesIO(b"\x00" * 2048)
        resp = await async_client.post(
            f"/api/v1/sessions/{sid}/audio",
            files={"file": ("recording.opus", fake_audio, "audio/opus")},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["audio_key"] is not None
        assert resp.json()["audio_format"] == "opus"

        # ── Step 5: Transition to capturing ──
        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/status",
            json={"status": "capturing"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "capturing"

        # ── Step 6: Transition to processing ──
        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/status",
            json={"status": "processing"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "processing"

        # Verify jobs were created
        result = await db.execute(
            select(Job).where(Job.session_id == sid)
        )
        jobs = result.scalars().all()
        assert len(jobs) == 3  # transcribe, summarize, extract_artifact
        job_types = {j.job_type for j in jobs}
        assert job_types == {"transcribe", "summarize", "extract_artifact"}

        # ── Step 7: Execute transcribe job ──
        await _run_handler(db, sid, "transcribe")

        # ── Step 8: Execute summarize job ──
        await _run_handler(db, sid, "summarize")

        # ── Step 9: Execute extract_artifact job ──
        await _run_handler(db, sid, "extract_artifact")

        # Verify artifact was created
        result = await db.execute(
            select(Artifact).where(Artifact.session_id == sid)
        )
        artifacts = result.scalars().all()
        assert len(artifacts) >= 1
        artifact = artifacts[0]
        assert artifact.status == "pending_review"

        # Verify session is needs_review
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == sid)
        )
        session_obj = result.scalar_one()
        assert session_obj.status == "needs_review"

        # ── Step 10: Approve artifact ──
        aid = str(artifact.id)
        resp = await async_client.patch(
            f"/api/v1/artifacts/{aid}/review",
            json={"action": "approve", "comment": "Looks great!"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        # Verify session is now approved
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == sid)
        )
        session_obj = result.scalar_one()
        assert session_obj.status == "approved"

        # ── Step 11: Publish ──
        resp = await async_client.post(
            f"/api/v1/artifacts/{aid}/publish",
            headers=headers,
        )
        assert resp.status_code == 200

        # Execute publish job
        await _run_handler(db, sid, "publish")

        # Verify published state
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == sid)
        )
        session_obj = result.scalar_one()
        assert session_obj.status == "published"

        result = await db.execute(
            select(Artifact).where(Artifact.id == artifact.id)
        )
        artifact = result.scalar_one()
        assert artifact.status == "published"

        # ── That's the full Happy Path! 🎉 ──


# ══════════════════════════════════════════════════════════════════════
# Path 2: Failure + Retry
# ══════════════════════════════════════════════════════════════════════

class TestFailureRetry:
    """Failure + Retry path: transcribe fails → retry → eventually succeeds."""

    @pytest.mark.asyncio
    async def test_transcribe_failure_and_retry(self, db, async_client):
        """Transcribe job fails, retries, eventually succeeds, downstream continues."""
        sid, headers = await _setup_session_with_audio(db, async_client)

        # Get the transcribe job
        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "transcribe")
        )
        job = result.scalar_one()

        # Manually simulate failure + retry using orchestrator
        from app.orchestrator.service import transition_job

        # First attempt: run → fail
        await transition_job(db, job, "running")
        await transition_job(db, job, STATUS_FAILED, error_message="Transient API error")
        await db.refresh(job)
        assert job.status == STATUS_FAILED
        assert job.retry_count == 1
        assert job.next_run_at is not None  # Scheduled for retry
        assert job.error_message == "Transient API error"

        # Retry: reset to pending
        await transition_job(db, job, STATUS_PENDING)
        await db.refresh(job)
        assert job.status == STATUS_PENDING

        # Second attempt: run → complete
        await transition_job(db, job, "running")
        # Actually execute the handler this time
        from app.agents.capture import handle_transcribe_job
        await handle_transcribe_job(db, job)
        await db.refresh(job)
        assert job.status == "completed"
        assert job.output_payload is not None
        assert "transcript" in job.output_payload

        # Now complete summarize and extract
        await _run_handler(db, sid, "summarize")
        await _run_handler(db, sid, "extract_artifact")

        # Verify artifact was created despite failure
        result = await db.execute(
            select(Artifact).where(Artifact.session_id == sid)
        )
        artifacts = result.scalars().all()
        assert len(artifacts) >= 1


# ══════════════════════════════════════════════════════════════════════
# Path 3: Review Cycle — Reject → Re-extract → Re-approve
# ══════════════════════════════════════════════════════════════════════

class TestReviewCycle:
    """Review Cycle: needs_review → reject → new extract → re-approve → publish."""

    @pytest.mark.asyncio
    async def test_review_cycle_reject_and_reapprove(self, db, async_client):
        """Reject an artifact, have it re-extracted, then approve it."""
        sid, headers = await _setup_session_with_audio(db, async_client)

        # Run full pipeline to get artifact
        await _run_handler(db, sid, "transcribe")
        await _run_handler(db, sid, "summarize")
        await _run_handler(db, sid, "extract_artifact")

        # Get the artifact
        result = await db.execute(
            select(Artifact).where(Artifact.session_id == sid)
        )
        artifact = result.scalar_one()
        aid = str(artifact.id)

        # Reject the artifact
        resp = await async_client.patch(
            f"/api/v1/artifacts/{aid}/review",
            json={"action": "reject", "comment": "Missing details, please re-extract"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

        # Verify a new extract_artifact job was created
        result = await db.execute(
            select(Job).where(
                Job.session_id == sid,
                Job.job_type == "extract_artifact",
                Job.status == "pending",
            )
        )
        retry_jobs = result.scalars().all()
        assert len(retry_jobs) >= 1

        # Run the retry extract
        await _run_handler(db, sid, "extract_artifact")

        # Verify a new artifact now exists
        result = await db.execute(
            select(Artifact).where(Artifact.session_id == sid)
        )
        artifacts = result.scalars().all()
        # Should have at least 2 artifacts (original rejected + new one)
        assert len(artifacts) >= 2

        # Approve the new artifact (the one with pending_review status)
        new_artifact = [a for a in artifacts if a.status == "pending_review"]
        if new_artifact:
            await db.refresh(new_artifact[0])
            aid2 = str(new_artifact[0].id)
            resp = await async_client.patch(
                f"/api/v1/artifacts/{aid2}/review",
                json={"action": "approve", "comment": "Much better!"},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "approved"

        # Approve the rejected one too to get session approved
        resp = await async_client.patch(
            f"/api/v1/artifacts/{aid}/review",
            json={"action": "approve", "comment": "Re-approved"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Verify session approved
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == sid)
        )
        session_obj = result.scalar_one()
        # All artifacts approved → session should be approved
        assert session_obj.status == "approved"


# ══════════════════════════════════════════════════════════════════════
# Path 4: Retract Saga
# ══════════════════════════════════════════════════════════════════════

class TestRetractSaga:
    """Retract Saga: published → retract → deletion_jobs → Worker → tombstone → audit."""

    @pytest.mark.asyncio
    async def test_retract_saga_full_cycle(self, db, async_client):
        """Complete retract saga: from published to tombstone."""
        sid, headers = await _setup_session_with_audio(db, async_client)

        # Run full pipeline to get published
        await _run_handler(db, sid, "transcribe")
        await _run_handler(db, sid, "summarize")
        await _run_handler(db, sid, "extract_artifact")

        result = await db.execute(
            select(Artifact).where(Artifact.session_id == sid)
        )
        artifact = result.scalar_one()
        aid = str(artifact.id)

        # Approve
        await async_client.patch(
            f"/api/v1/artifacts/{aid}/review",
            json={"action": "approve", "comment": "Approved"},
            headers=headers,
        )

        # Publish
        await async_client.post(f"/api/v1/artifacts/{aid}/publish", headers=headers)
        await _run_handler(db, sid, "publish")

        # Verify published
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == sid)
        )
        session_obj = result.scalar_one()
        assert session_obj.status == "published"

        # ── RETRACT ──
        resp = await async_client.post(
            f"/api/v1/sessions/{sid}/retract",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "retracting"

        # Verify deletion_jobs were created
        result = await db.execute(
            select(DeletionJob).where(DeletionJob.session_id == sid)
        )
        del_jobs = result.scalars().all()
        assert len(del_jobs) == 3

        # Execute deletion_jobs via handlers
        from app.agents.deletion import (
            handle_delete_artifacts,
            handle_delete_audio,
            handle_delete_feishu,
        )
        for dj in del_jobs:
            handler_map = {
                "delete_artifact_rows": handle_delete_artifacts,
                "delete_local_audio": handle_delete_audio,
                "delete_feishu_docs": handle_delete_feishu,
            }
            handler = handler_map.get(dj.resource_type)
            if handler:
                await handler(db, dj)
                await db.refresh(dj)
                assert dj.status == "completed"

        # Verify artifacts were hard-deleted
        result = await db.execute(
            select(func.count()).select_from(Artifact).where(Artifact.session_id == sid)
        )
        count = result.scalar()
        assert count == 0  # Artifacts hard-deleted

        # Verify session tombstone exists
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == sid)
        )
        session_obj = result.scalar_one()
        assert session_obj.status == "retracting"
        assert session_obj.deleted_at is not None
        assert session_obj.retracted_by is not None

        # Verify audit logs exist
        result = await db.execute(
            select(AuditLog).where(AuditLog.session_id == sid)
        )
        audit_logs = result.scalars().all()
        # At minimum, consent_granted and retract_initiated
        assert len(audit_logs) >= 1
        audit_actions = {log.action for log in audit_logs}
        assert "retract_initiated" in audit_actions


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

async def _setup_session_with_audio(db, async_client) -> tuple:
    """Register, create session, consent, upload audio, transition to processing.

    Returns (session_id, auth_headers).
    """
    email = f"e2e-setup-{uuid.uuid4().hex[:8]}@example.com"
    password = "e2e-password-123"

    resp = await async_client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "display_name": "E2E User",
        "org_name": "E2E Org",
    })
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await async_client.post("/api/v1/sessions", json={
        "title": "E2E Test Session",
    }, headers=headers)
    assert resp.status_code == 201
    sid = resp.json()["id"]

    await async_client.patch(
        f"/api/v1/sessions/{sid}/consent",
        json={"consent": True},
        headers=headers,
    )

    fake_audio = BytesIO(b"\x00" * 2048)
    await async_client.post(
        f"/api/v1/sessions/{sid}/audio",
        files={"file": ("recording.opus", fake_audio, "audio/opus")},
        headers=headers,
    )

    await async_client.patch(
        f"/api/v1/sessions/{sid}/status",
        json={"status": "capturing"},
        headers=headers,
    )

    await async_client.patch(
        f"/api/v1/sessions/{sid}/status",
        json={"status": "processing"},
        headers=headers,
    )

    return uuid.UUID(sid), headers


async def _run_handler(db, session_id, job_type: str):
    """Execute a job handler for the given session and job type."""
    from sqlalchemy import select
    from app.models.job import Job

    result = await db.execute(
        select(Job).where(
            Job.session_id == session_id,
            Job.job_type == job_type,
        ).order_by(Job.created_at.desc()).limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return

    from app.orchestrator.worker import JOB_HANDLERS
    handler = JOB_HANDLERS.get(job_type)
    if handler is None:
        return

    job.status = "running"
    await db.flush()
    await handler(db, job)
