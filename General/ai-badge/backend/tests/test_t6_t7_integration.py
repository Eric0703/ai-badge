"""T6 Capture + T7 Distiller Integration Tests.

Covers:
  - T6.1: Full pipeline trigger (upload → processing → jobs created)
  - T6.2: Capture agent handler with mocked provider
  - T7.1: Summarize agent handler with mocked LLM
  - T7.2: Extract artifact handler with mocked LLM
"""

import asyncio
import io
import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.agents.capture import handle_transcribe_job
from app.agents.distiller import handle_summarize_job, handle_extract_artifact_job, set_llm
from app.config import settings
from app.db.session import async_session_factory
from app.main import app
from app.models.artifact import Artifact
from app.models.job import Job
from app.models.session import Session as SessionModel
from app.orchestrator.service import create_jobs_for_session
from app.providers.base import LLMProvider, TranscriptionProvider, TranscriptResult
from sqlalchemy import select

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def auth_headers(async_client):
    """Register a test user and return auth headers."""
    email = f"test-t6-{uuid.uuid4().hex[:8]}@example.com"
    resp = await async_client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "testpass1234",
        "display_name": "T6 Test User",
        "org_name": "T6 Test Org",
    })
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def session_id(async_client, auth_headers):
    """Create a session with consent granted and audio uploaded."""
    # Create session
    resp = await async_client.post("/api/v1/sessions", json={
        "title": "T6 Integration Test",
    }, headers=auth_headers)
    assert resp.status_code == 201, f"Create session failed: {resp.text}"
    sid = resp.json()["id"]

    # Grant consent
    resp = await async_client.patch(
        f"/api/v1/sessions/{sid}/consent",
        json={"consent": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Transition to capturing
    resp = await async_client.patch(
        f"/api/v1/sessions/{sid}/status",
        json={"status": "capturing"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Upload audio
    fake_audio = io.BytesIO(b"fake-opus-audio-data")
    resp = await async_client.post(
        f"/api/v1/sessions/{sid}/audio",
        files={"file": ("test.opus", fake_audio, "audio/opus")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["audio_key"] is not None

    return sid


# ── T6.1: Full Pipeline Trigger ───────────────────────────────────────


class TestT6FullPipeline:
    """Test that transitioning to processing creates the full job pipeline."""

    @pytest.mark.asyncio
    async def test_transition_to_processing_creates_jobs(
        self, async_client, auth_headers, session_id
    ):
        """When session transitions to processing, 3 jobs should be created."""
        # Transition to processing
        resp = await async_client.patch(
            f"/api/v1/sessions/{session_id}/status",
            json={"status": "processing"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

        # Verify jobs exist
        async with async_session_factory() as s:
            r = await s.execute(
                select(Job).where(
                    Job.session_id == uuid.UUID(session_id)
                ).order_by(Job.created_at)
            )
            jobs = r.scalars().all()

        job_types = [j.job_type for j in jobs]
        assert "transcribe" in job_types, f"Expected transcribe job, got {job_types}"
        assert "summarize" in job_types, f"Expected summarize job, got {job_types}"
        assert "extract_artifact" in job_types, f"Expected extract_artifact job, got {job_types}"
        assert len(jobs) == 3, f"Expected 3 jobs, got {len(jobs)}"
        for j in jobs:
            assert j.status == "pending", f"Job {j.job_type} status={j.status}, expected pending"

    @pytest.mark.asyncio
    async def test_processing_without_audio_fails(
        self, async_client, auth_headers
    ):
        """Transitioning to processing without audio should return 400."""
        # Create session without audio
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "No Audio Test",
        }, headers=auth_headers)
        assert resp.status_code == 201
        sid = resp.json()["id"]

        # Grant consent
        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/consent",
            json={"consent": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Try to go straight to processing (skip capturing/upload)
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
        assert resp.status_code == 400
        assert "Audio must be uploaded" in resp.json()["detail"]


# ── T6.2: Capture Agent Handler ───────────────────────────────────────


class MockTranscriber(TranscriptionProvider):
    """Mock transcription provider for testing."""

    async def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptResult:
        return TranscriptResult(
            transcript="This is a test transcript from the mock provider.",
            segments=[
                {"start": 0.0, "end": 1.0, "text": "This is a test"},
                {"start": 1.0, "end": 2.0, "text": "transcript from the mock provider."},
            ],
            language="en",
        )


class TestT6CaptureAgent:
    """Test the transcribe job handler."""

    @pytest.mark.asyncio
    async def test_handle_transcribe_job(self, async_client, auth_headers, session_id):
        """Worker handler should transcribe and update job status to completed."""
        # Transition to processing to create jobs
        resp = await async_client.patch(
            f"/api/v1/sessions/{session_id}/status",
            json={"status": "processing"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Get the transcribe job
        async with async_session_factory() as s:
            r = await s.execute(
                select(Job).where(
                    Job.session_id == uuid.UUID(session_id),
                    Job.job_type == "transcribe",
                )
            )
            job = r.scalar_one()

        # Actually, we need to mock the provider first.
        # Import and monkey-patch the capture module's transcriber.
        import app.capture.service as cap_service
        original = cap_service.get_transcriber()
        cap_service.set_transcriber(MockTranscriber())

        try:
            async with async_session_factory() as s:
                await handle_transcribe_job(s, job)
                await s.commit()

                # Verify job completed
                r = await s.execute(select(Job).where(Job.id == job.id))
                updated = r.scalar_one()
                assert updated.status == "completed"
                assert updated.output_payload is not None
                assert "transcript" in updated.output_payload
                assert updated.output_payload["transcript"] == "This is a test transcript from the mock provider."
                assert len(updated.output_payload["segments"]) == 2
                assert updated.output_payload["language"] == "en"
        finally:
            cap_service.set_transcriber(original)

    @pytest.mark.asyncio
    async def test_transcribe_job_fails_without_audio(self, async_client, auth_headers):
        """Transcribe job should raise error if session has no audio_key."""
        # Create session without audio
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "No Audio For Transcribe",
        }, headers=auth_headers)
        assert resp.status_code == 201
        sid = resp.json()["id"]

        # Manually create a transcribe job (bypass normal flow)
        sid_uuid = uuid.UUID(sid)
        async with async_session_factory() as s:
            from app.orchestrator.service import create_jobs_for_session
            # Force-create via orchestrator but session has no audio_key
            import app.capture.service as cap_service
            cap_service.set_transcriber(MockTranscriber())

            try:
                # Create session first with audio_key=None
                r = await s.execute(select(SessionModel).where(SessionModel.id == sid_uuid))
                sess = r.scalar_one()
                sess.status = "processing"
                await s.commit()

                # Create jobs (orchestrator won't check for audio)
                jobs = await create_jobs_for_session(s, sid_uuid)
                await s.commit()
                transcribe_job = [j for j in jobs if j.job_type == "transcribe"][0]

                # Should raise ValueError
                with pytest.raises(ValueError, match="has no audio_key"):
                    await handle_transcribe_job(s, transcribe_job)
            finally:
                cap_service.set_transcriber(MockTranscriber())


# ── T7.1: Distiller Summarize Agent ────────────────────────────────────


class MockLLM(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, response: dict | None = None):
        self.response = response or {
            "summary": "Test summary of the meeting transcript.",
            "artifact_type": "meeting_minutes",
            "title": "Weekly Standup 2026-06-11",
        }
        self.last_prompt = None
        self.last_schema = None

    async def complete(
        self, prompt: str, schema: dict | None = None, model: str | None = None,
        temperature: float = 0.7, max_tokens: int = 4096,
    ) -> dict:
        self.last_prompt = prompt
        self.last_schema = schema
        return self.response

    async def chat_stream(self, messages, model=None, temperature=0.7, max_tokens=4096):
        yield "mock stream"


class TestT7DistillerAgent:
    """Test the summarize and extract_artifact job handlers."""

    @pytest.mark.asyncio
    async def test_handle_summarize_job(self, async_client, auth_headers, session_id):
        """Worker handler should call LLM and store summary + artifact_type."""
        # Transition to processing to create jobs
        resp = await async_client.patch(
            f"/api/v1/sessions/{session_id}/status",
            json={"status": "processing"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        sid_uuid = uuid.UUID(session_id)

        # First, complete the transcribe job with mock transcript
        async with async_session_factory() as s:
            r = await s.execute(
                select(Job).where(
                    Job.session_id == sid_uuid,
                    Job.job_type == "transcribe",
                )
            )
            transcribe_job = r.scalar_one()
            transcribe_job.status = "completed"
            transcribe_job.output_payload = {
                "transcript": "Alice: We need to ship the feature. Bob: Agreed, by Friday. Alice: I'll update the docs.",
                "segments": [],
                "language": "en",
            }
            await s.commit()

        # Now test summarize
        mock_llm = MockLLM()
        set_llm(mock_llm)

        try:
            async with async_session_factory() as s:
                r = await s.execute(
                    select(Job).where(
                        Job.session_id == sid_uuid,
                        Job.job_type == "summarize",
                    )
                )
                summarize_job = r.scalar_one()

                await handle_summarize_job(s, summarize_job)
                await s.commit()

                # Verify
                r = await s.execute(select(Job).where(Job.id == summarize_job.id))
                updated = r.scalar_one()
                assert updated.status == "completed"
                assert updated.output_payload["summary"] == "Test summary of the meeting transcript."
                assert updated.output_payload["artifact_type"] == "meeting_minutes"
                assert updated.output_payload["title"] == "Weekly Standup 2026-06-11"
                assert "transcript" in mock_llm.last_prompt
        finally:
            set_llm(None)

    @pytest.mark.asyncio
    async def test_handle_extract_artifact_job(self, async_client, auth_headers, session_id):
        """Worker handler should create Artifact row in DB."""
        # Setup: complete transcribe + summarize jobs
        resp = await async_client.patch(
            f"/api/v1/sessions/{session_id}/status",
            json={"status": "processing"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        sid_uuid = uuid.UUID(session_id)

        async with async_session_factory() as s:
            # Complete transcribe
            r = await s.execute(select(Job).where(
                Job.session_id == sid_uuid, Job.job_type == "transcribe"
            ))
            tj = r.scalar_one()
            tj.status = "completed"
            tj.output_payload = {
                "transcript": "Standup: decided to ship on Friday. Alice will update docs.",
                "segments": [],
                "language": "en",
            }

            # Complete summarize
            r = await s.execute(select(Job).where(
                Job.session_id == sid_uuid, Job.job_type == "summarize"
            ))
            sj = r.scalar_one()
            sj.status = "completed"
            sj.output_payload = {
                "summary": "Team decided to ship on Friday.",
                "artifact_type": "meeting_minutes",
                "title": "Shipping Decision",
            }
            await s.commit()

        # Mock LLM for extract
        extract_response = {
            "title": "Shipping Decision",
            "date": "2026-06-11",
            "participants": ["Alice", "Bob"],
            "summary": "Team decided to ship on Friday.",
            "key_points": ["Ship on Friday", "Alice updates docs"],
            "decisions": [{"decision": "Ship Friday", "rationale": "Ready"}],
            "action_items": [{"task": "Update docs", "assignee": "Alice", "due_date": "Friday"}],
        }
        mock_llm = MockLLM(response=extract_response)
        set_llm(mock_llm)

        try:
            async with async_session_factory() as s:
                r = await s.execute(select(Job).where(
                    Job.session_id == sid_uuid, Job.job_type == "extract_artifact"
                ))
                ej = r.scalar_one()

                await handle_extract_artifact_job(s, ej)
                await s.commit()

                # Verify job completed
                r = await s.execute(select(Job).where(Job.id == ej.id))
                updated = r.scalar_one()
                assert updated.status == "completed"
                assert updated.output_payload["artifact_type"] == "meeting_minutes"

                # Verify Artifact created in DB
                r = await s.execute(select(Artifact).where(
                    Artifact.session_id == sid_uuid
                ))
                artifacts = r.scalars().all()
                assert len(artifacts) == 1
                artifact = artifacts[0]
                assert artifact.artifact_type == "meeting_minutes"
                assert artifact.title == "Shipping Decision"
                assert artifact.status == "pending_review"
                assert artifact.content == extract_response

                # Verify session status updated
                r = await s.execute(select(SessionModel).where(
                    SessionModel.id == sid_uuid
                ))
                sess = r.scalar_one()
                assert sess.status == "needs_review"
        finally:
            set_llm(None)

    @pytest.mark.asyncio
    async def test_summarize_without_transcribe_fails(self, async_client, auth_headers, session_id):
        """Summarize should fail if transcribe job is not completed."""
        resp = await async_client.patch(
            f"/api/v1/sessions/{session_id}/status",
            json={"status": "processing"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        sid_uuid = uuid.UUID(session_id)
        mock_llm = MockLLM()
        set_llm(mock_llm)

        try:
            async with async_session_factory() as s:
                r = await s.execute(select(Job).where(
                    Job.session_id == sid_uuid, Job.job_type == "summarize"
                ))
                sj = r.scalar_one()

                with pytest.raises(ValueError, match="No completed transcribe job"):
                    await handle_summarize_job(s, sj)
        finally:
            set_llm(None)
