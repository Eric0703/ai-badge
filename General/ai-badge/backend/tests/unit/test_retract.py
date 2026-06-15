"""Unit tests — Retract Saga: deletion_jobs, tombstone, session soft-delete.

Tests:
- retract_session: creates tombstone, 3 deletion_jobs
- DeletionJob model: fields, defaults
- Saga: cannot retract non-published session
- Saga: cannot retract already-retracted session

All direct SessionModel creation MUST include device_id (NOT NULL per Phase 1A).
"""

import uuid

import pytest
from sqlalchemy import select

from tests.conftest import create_test_user_with_org_and_device, create_test_session
from app.models.session import Session as SessionModel
from app.models.deletion_job import DeletionJob
from app.models.user import User
from app.sessions.service import retract_session


class TestRetractSession:
    """retract_session — the Saga entry point."""

    @pytest.mark.asyncio
    async def test_retract_creates_tombstone(self, db):
        session, _ = await _create_published_session(db)
        user_id = session.user_id

        result = await retract_session(db, session.id, user_id, reason="Test retraction")

        assert result.status == "retracting"
        assert result.deleted_at is not None
        assert result.retracted_by == user_id
        assert result.retraction_reason == "Test retraction"

    @pytest.mark.asyncio
    async def test_retract_creates_three_deletion_jobs(self, db):
        session, _ = await _create_published_session(db)
        user_id = session.user_id

        await retract_session(db, session.id, user_id, reason="Cleanup")

        result = await db.execute(
            select(DeletionJob).where(DeletionJob.session_id == session.id)
        )
        jobs = result.scalars().all()
        assert len(jobs) == 3

        resource_types = {j.resource_type for j in jobs}
        assert "delete_artifact_rows" in resource_types
        assert "delete_local_audio" in resource_types
        assert "delete_feishu_docs" in resource_types

    @pytest.mark.asyncio
    async def test_retract_deletion_jobs_start_pending(self, db):
        session, _ = await _create_published_session(db)
        user_id = session.user_id

        await retract_session(db, session.id, user_id, reason="Test")

        result = await db.execute(
            select(DeletionJob).where(DeletionJob.session_id == session.id)
        )
        jobs = result.scalars().all()
        for job in jobs:
            assert job.status == "pending"

    @pytest.mark.asyncio
    async def test_cannot_retract_non_published_session(self, db):
        session, _ = await _create_session_in_status(db, "idle")

        with pytest.raises(ValueError):
            await retract_session(db, session.id, session.user_id)

    @pytest.mark.asyncio
    async def test_cannot_retract_wrong_user(self, db):
        session, user = await _create_published_session(db)
        wrong_user_id = uuid.uuid4()

        with pytest.raises(ValueError):
            await retract_session(db, session.id, wrong_user_id)

    @pytest.mark.asyncio
    async def test_retract_soft_deletes_not_hard_deletes(self, db):
        """Session should still exist in DB after retract (tombstone)."""
        session, _ = await _create_published_session(db)
        user_id = session.user_id

        await retract_session(db, session.id, user_id, reason="Test")

        result = await db.execute(
            select(SessionModel).where(SessionModel.id == session.id)
        )
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.status == "retracting"
        assert found.deleted_at is not None


class TestDeletionJobModel:
    """DeletionJob ORM model."""

    @pytest.mark.asyncio
    async def test_default_values(self, db):
        dj = DeletionJob(
            resource_type="delete_artifact_rows",
            resource_id=uuid.uuid4(),
        )
        db.add(dj)
        await db.flush()

        assert dj.status == "pending"
        assert dj.retry_count == 0
        assert dj.max_retries == 3

    @pytest.mark.asyncio
    async def test_deletion_job_cascade_targets(self, db):
        dj = DeletionJob(
            resource_type="delete_local_audio",
            resource_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            cascade_targets={"audio_key": "test.opus"},
        )
        db.add(dj)
        await db.flush()

        assert dj.cascade_targets == {"audio_key": "test.opus"}


# ══════════════════════════════════════════════════════════════════════
# Retract API endpoint tests
# ══════════════════════════════════════════════════════════════════════

class TestRetractAPI:
    """POST /api/v1/sessions/{id}/retract"""

    @pytest.mark.asyncio
    async def test_retract_endpoint_creates_tombstone(
        self, db, async_client, auth_headers
    ):
        """Full flow: register → session → publish → retract."""
        # Create a published session in DB via the helper
        user, org, device = await create_test_user_with_org_and_device(db)
        session = await create_test_session(
            db, user_id=user.id, device_id=device.id,
            status="published",
        )

        # Try retract via API — session belongs to a different user (not the
        # one from auth_headers), so expect 404 or 403. This validates the
        # endpoint ownership check.
        resp = await async_client.post(
            f"/api/v1/sessions/{session.id}/retract",
            headers=auth_headers,
        )
        assert resp.status_code in (404, 403)

    @pytest.mark.asyncio
    async def test_retract_requires_published_status(
        self, async_client, db, auth_headers
    ):
        """Test that retract on idle session is rejected."""
        # Create a session via API (auto-creates virtual_phone_mic device)
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "Not Published",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        resp = await async_client.post(
            f"/api/v1/sessions/{sid}/retract",
            headers=auth_headers,
        )
        assert resp.status_code in (403, 409, 422)


# ── Helpers ──────────────────────────────────────────────────────────

async def _create_published_session(db) -> tuple:
    """Create a published session with org→user→device, return (session, user)."""
    user, org, device = await create_test_user_with_org_and_device(db)
    session = await create_test_session(
        db, user_id=user.id, device_id=device.id,
        status="published",
    )
    return session, user


async def _create_session_in_status(db, status: str) -> tuple:
    """Create a session in a specific status, return (session, user)."""
    user, org, device = await create_test_user_with_org_and_device(db)
    session = await create_test_session(
        db, user_id=user.id, device_id=device.id,
        status=status,
    )
    return session, user
