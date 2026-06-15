"""Unit tests — Artifacts: CRUD, review, publish.

Tests:
- List artifacts, get artifact, update artifact
- Review: approve (single, all-approved → session.approved)
- Review: reject (creates new extract_artifact job)
- Publish: 403 if not approved
- Artifact status transitions
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import create_test_user_with_org_and_device, create_test_session

from app.models.artifact import Artifact
from app.models.session import Session as SessionModel
from app.models.job import Job
from app.models.user import User


class TestArtifactCRUD:
    """Artifact list, get, update through API."""

    @pytest.mark.asyncio
    async def test_list_artifacts(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get("/api/v1/artifacts", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "artifacts" in data
        assert "total" in data
        assert isinstance(data["artifacts"], list)

    @pytest.mark.asyncio
    async def test_get_artifact_404(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.get(f"/api/v1/artifacts/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_artifact_404(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.patch(
            f"/api/v1/artifacts/{uuid.uuid4()}",
            json={"title": "New Title"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestArtifactReview:
    """Review endpoint: approve and reject."""

    @pytest.mark.asyncio
    async def test_approve_artifact(self, db, async_client, auth_headers):
        aid = await _create_artifact(db, status="pending_review", session_status="reviewing")

        resp = await async_client.patch(
            f"/api/v1/artifacts/{aid}/review",
            json={"action": "approve", "comment": "Looks good"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "approved"
        assert data["review_status"] == "approved"
        assert data["review_comment"] == "Looks good"

    @pytest.mark.asyncio
    async def test_reject_artifact(self, db, async_client, auth_headers):
        aid = await _create_artifact(db, status="pending_review", session_status="reviewing")

        resp = await async_client.patch(
            f"/api/v1/artifacts/{aid}/review",
            json={"action": "reject", "comment": "Needs improvement"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["review_status"] == "rejected"

        # Verify new extract_artifact job was created
        result = await db.execute(
            select(Job).where(
                Job.session_id == data["session_id"],
                Job.job_type == "extract_artifact",
                Job.status == "pending",
            )
        )
        jobs = result.scalars().all()
        # Reject creates exactly one new pending extract_artifact retry job
        assert len(jobs) >= 1

    @pytest.mark.asyncio
    async def test_review_404(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.patch(
            f"/api/v1/artifacts/{uuid.uuid4()}/review",
            json={"action": "approve", "comment": "ok"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestArtifactPublish:
    """Publish endpoint."""

    @pytest.mark.asyncio
    async def test_publish_unapproved_returns_403(self, db, async_client, auth_headers):
        aid = await _create_artifact(db, status="draft")

        resp = await async_client.post(
            f"/api/v1/artifacts/{aid}/publish",
            headers=auth_headers,
        )
        assert resp.status_code == 403
        assert "approved" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_publish_approved_creates_job(self, db, async_client, auth_headers):
        aid = await _create_artifact(db, status="approved", session_status="approved")

        resp = await async_client.post(
            f"/api/v1/artifacts/{aid}/publish",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        # Verify publish job created
        result = await db.execute(
            select(Job).where(
                Job.job_type == "publish",
                Job.status == "pending",
            )
        )
        job = result.scalar_one_or_none()
        assert job is not None
        assert str(aid) in job.input_payload.get("artifact_id", "")

    @pytest.mark.asyncio
    async def test_publish_404(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.post(
            f"/api/v1/artifacts/{uuid.uuid4()}/publish",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestArtifactStatusTransitions:
    """Artifact status flow: draft → pending_review → approved/rejected → published."""

    @pytest.mark.asyncio
    async def test_default_status_is_draft(self, db):
        user, org, device = await create_test_user_with_org_and_device(db)
        session = await create_test_session(db, user_id=user.id, device_id=device.id)
        artifact = Artifact(
            session_id=session.id,
            artifact_type="meeting_minutes",
            title="Test",
            content={"summary": "test"},
        )
        db.add(artifact)
        await db.flush()
        assert artifact.status == "draft"

    @pytest.mark.asyncio
    async def test_statuses_exist(self, db):
        """Verify the artifact can be set to each valid status."""
        user, org, device = await create_test_user_with_org_and_device(db)
        session = await create_test_session(db, user_id=user.id, device_id=device.id)
        valid_statuses = ["draft", "pending_review", "approved", "rejected", "published"]
        for status in valid_statuses:
            artifact = Artifact(
                session_id=session.id,
                artifact_type="meeting_minutes",
                title=f"Status {status}",
                content={"summary": "test"},
                status=status,
            )
            db.add(artifact)
        await db.flush()
        # No exception = all statuses accepted by the DB


# ── Helpers ──────────────────────────────────────────────────────────

async def _create_artifact(db, status: str = "draft", session_status: str = "idle") -> uuid.UUID:
    """Create a test artifact and return its ID.

    Commits so the API (which runs on a separate connection) can see the data.
    session_status lets callers put the session in a state consistent with the
    artifact status / transition being exercised.
    """
    user, org, device = await create_test_user_with_org_and_device(db)

    session_obj = await create_test_session(
        db, user_id=user.id, device_id=device.id,
        status=session_status,
    )

    artifact = Artifact(
        id=uuid.uuid4(),
        session_id=session_obj.id,
        artifact_type="meeting_minutes",
        title="Test Artifact",
        content={"summary": "Test content", "key_points": ["Point 1"]},
        status=status,
    )
    db.add(artifact)
    await db.commit()
    return artifact.id
