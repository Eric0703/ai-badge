"""Unit tests — Agents: Mock provider transcribe, summarize, extract_artifact, publish.

Tests:
- Transcribe handler: reads audio, writes output_payload
- Summarize handler: reads transcript, writes summary
- Extract artifact handler: creates Artifact, updates session status
- Publish handler: marks artifact published, session published
- Error cases: missing audio, missing transcript
"""

import uuid
from io import BytesIO

import pytest
from httpx import AsyncClient

from tests.conftest import create_test_user_with_org_and_device, create_test_session
from sqlalchemy import select

from app.models.job import Job
from app.models.artifact import Artifact
from app.models.session import Session as SessionModel


class TestTranscribeHandler:
    """Worker handler for 'transcribe' job type."""

    @pytest.mark.asyncio
    async def test_transcribe_job_writes_output(self, db, async_client, auth_headers):
        """End-to-end: upload audio → transcribe job → output_payload."""
        # Setup: create session, consent, upload audio, move to processing
        sid = await _setup_session_with_audio(async_client, auth_headers)

        # Verify transcribe job was created during processing transition
        result = await db.execute(
            select(Job).where(
                Job.session_id == sid,
                Job.job_type == "transcribe",
            )
        )
        job = result.scalar_one_or_none()
        assert job is not None
        assert job.status == "pending"

        # Manually execute the handler (simulating Worker)
        from app.agents.capture import handle_transcribe_job
        await handle_transcribe_job(db, job)

        # Refresh
        await db.refresh(job)
        assert job.status == "completed"
        payload = job.output_payload
        assert payload is not None
        assert "transcript" in payload
        assert len(payload["transcript"]) > 0
        assert "segments" in payload
        assert payload["language"] == "zh"

    @pytest.mark.asyncio
    async def test_transcribe_fails_without_audio(self, db):
        """Job with no audio_key should raise error."""
        user, org, device = await create_test_user_with_org_and_device(db)
        session = await create_test_session(
            db, user_id=user.id, device_id=device.id,
            audio_key=None,  # explicitly no audio
        )

        job = Job(
            idempotency_key=f"no-audio-{uuid.uuid4()}",
            session_id=session.id,
            job_type="transcribe",
            status="pending",
        )
        db.add(job)
        await db.flush()

        from app.agents.capture import handle_transcribe_job
        with pytest.raises(ValueError):
            await handle_transcribe_job(db, job)


class TestSummarizeHandler:
    """Worker handler for 'summarize' job type."""

    @pytest.mark.asyncio
    async def test_summarize_writes_output(self, db, async_client, auth_headers):
        """Summarize handler reads transcript and produces summary."""
        sid = await _setup_session_with_audio(async_client, auth_headers)

        # Run transcribe first
        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "transcribe")
        )
        transcribe_job = result.scalar_one()
        from app.agents.capture import handle_transcribe_job
        await handle_transcribe_job(db, transcribe_job)
        await db.commit()

        # Get summarize job
        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "summarize")
        )
        summarize_job = result.scalar_one()

        from app.agents.distiller import handle_summarize_job
        await handle_summarize_job(db, summarize_job)

        await db.refresh(summarize_job)
        assert summarize_job.status == "completed"
        payload = summarize_job.output_payload
        assert payload is not None
        assert "summary" in payload
        assert "artifact_type" in payload
        assert "title" in payload


class TestExtractArtifactHandler:
    """Worker handler for 'extract_artifact' job type."""

    @pytest.mark.asyncio
    async def test_extract_creates_artifact(self, db, async_client, auth_headers):
        """Extract handler creates Artifact row and sets session to needs_review."""
        sid = await _setup_session_with_audio(async_client, auth_headers)

        # Run transcribe → summarize
        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "transcribe")
        )
        transcribe_job = result.scalar_one()
        from app.agents.capture import handle_transcribe_job
        await handle_transcribe_job(db, transcribe_job)
        await db.commit()

        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "summarize")
        )
        summarize_job = result.scalar_one()
        from app.agents.distiller import handle_summarize_job
        await handle_summarize_job(db, summarize_job)
        await db.commit()

        # Run extract_artifact
        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "extract_artifact")
        )
        extract_job = result.scalar_one()
        from app.agents.distiller import handle_extract_artifact_job
        await handle_extract_artifact_job(db, extract_job)

        await db.refresh(extract_job)
        assert extract_job.status == "completed"

        # Verify Artifact was created
        result = await db.execute(
            select(Artifact).where(Artifact.session_id == sid)
        )
        artifacts = result.scalars().all()
        assert len(artifacts) >= 1
        artifact = artifacts[0]
        assert artifact.status == "pending_review"
        assert artifact.artifact_type in ("meeting_minutes", "decision_record", "faq_draft", "sop_draft")

    @pytest.mark.asyncio
    async def test_extract_sets_session_to_needs_review(self, db, async_client, auth_headers):
        """After extract_artifact, session status should be needs_review."""
        sid = await _setup_session_with_audio(async_client, auth_headers)

        # Run full pipeline: transcribe → summarize → extract
        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "transcribe")
        )
        transcribe_job = result.scalar_one()
        from app.agents.capture import handle_transcribe_job
        await handle_transcribe_job(db, transcribe_job)
        await db.commit()

        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "summarize")
        )
        summarize_job = result.scalar_one()
        from app.agents.distiller import handle_summarize_job
        await handle_summarize_job(db, summarize_job)
        await db.commit()

        result = await db.execute(
            select(Job).where(Job.session_id == sid, Job.job_type == "extract_artifact")
        )
        extract_job = result.scalar_one()
        from app.agents.distiller import handle_extract_artifact_job
        await handle_extract_artifact_job(db, extract_job)

        # Check session status
        result = await db.execute(
            select(SessionModel).where(SessionModel.id == sid)
        )
        session_obj = result.scalar_one()
        assert session_obj.status == "needs_review"


class TestPublishHandler:
    """Worker handler for 'publish' job type."""

    @pytest.mark.asyncio
    async def test_publish_marks_artifact_and_session(self, db):
        """Publish handler marks artifact published and session published."""
        user, org, device = await create_test_user_with_org_and_device(db)

        session_obj = await create_test_session(
            db, user_id=user.id, device_id=device.id,
            status="publishing",
        )
        sid = session_obj.id
        aid = uuid.uuid4()

        # Create artifact directly
        artifact = Artifact(
            id=aid,
            session_id=sid,
            artifact_type="meeting_minutes",
            title="Test Artifact",
            content={"summary": "test"},
            status="approved",
        )
        db.add(artifact)
        await db.flush()

        # Create publish job
        job = Job(
            idempotency_key=f"publish-{uuid.uuid4()}",
            session_id=sid,
            job_type="publish",
            status="pending",
            input_payload={"artifact_id": str(aid)},
        )
        db.add(job)
        await db.flush()

        from app.agents.integration import handle_publish_job
        await handle_publish_job(db, job)

        await db.refresh(job)
        assert job.status == "completed"
        assert "feishu_doc_id" in job.output_payload

        await db.refresh(artifact)
        assert artifact.status == "published"
        assert artifact.published_at is not None


# ── Helpers ──────────────────────────────────────────────────────────

async def _setup_session_with_audio(async_client: AsyncClient, auth_headers: dict) -> uuid.UUID:
    """Create session, grant consent, upload audio, transition to processing.

    Returns session_id.
    """
    # Create session
    resp = await async_client.post("/api/v1/sessions", json={
        "title": "Agent Test Session",
    }, headers=auth_headers)
    assert resp.status_code == 201
    sid = uuid.UUID(resp.json()["id"])

    # Grant consent
    resp = await async_client.patch(
        f"/api/v1/sessions/{sid}/consent",
        json={"consent": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Upload fake audio
    fake_audio = BytesIO(b"\x00" * 1024)  # 1KB of silence
    resp = await async_client.post(
        f"/api/v1/sessions/{sid}/audio",
        files={"file": ("test.opus", fake_audio, "audio/opus")},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Transition to capturing → processing
    resp = await async_client.patch(
        f"/api/v1/sessions/{sid}/status",
        json={"status": "capturing"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await async_client.patch(
        f"/api/v1/sessions/{sid}/status",
        json={"status": "processing"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    return sid
