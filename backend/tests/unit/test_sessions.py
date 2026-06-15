"""Unit tests — Sessions module: state machine, consent, status transitions.

Tests:
- SessionStatus enum values
- can_transition: all valid transitions, illegal transitions
- Consent requirement for capturing
- API: create session, list sessions, get session, update status, cancel
"""

import uuid

import pytest
from httpx import AsyncClient

from app.sessions.service import SessionStatus, can_transition


# ══════════════════════════════════════════════════════════════════════
# State machine logic tests
# ══════════════════════════════════════════════════════════════════════

class TestSessionStatus:
    """SessionStatus enum and values."""

    def test_all_ddl_statuses_present(self):
        """Verify all DDL-defined statuses exist in the enum."""
        expected = {
            "idle", "capturing", "paused", "processing", "processing_failed",
            "needs_review", "reviewing", "approved",
            "publishing", "publish_failed", "published",
            "retracting", "retracted", "cancelled",
        }
        actual = {s.value for s in SessionStatus}
        assert expected == actual

    def test_default_status_is_idle(self):
        assert SessionStatus.IDLE.value == "idle"


class TestCanTransition:
    """State transition validation."""

    # ── Valid transitions ──────────────────────────────────────────

    def test_idle_to_capturing_with_consent(self):
        ok, reason = can_transition(SessionStatus.IDLE, SessionStatus.CAPTURING, consent_granted=True)
        assert ok is True
        assert reason == ""

    def test_idle_to_cancelled(self):
        ok, reason = can_transition(SessionStatus.IDLE, SessionStatus.CANCELLED)
        assert ok is True

    def test_capturing_to_paused(self):
        ok, reason = can_transition(SessionStatus.CAPTURING, SessionStatus.PAUSED)
        assert ok is True

    def test_capturing_to_processing(self):
        ok, reason = can_transition(SessionStatus.CAPTURING, SessionStatus.PROCESSING)
        assert ok is True

    def test_paused_to_capturing(self):
        ok, reason = can_transition(SessionStatus.PAUSED, SessionStatus.CAPTURING, consent_granted=True)
        assert ok is True

    def test_processing_to_needs_review(self):
        ok, reason = can_transition(SessionStatus.PROCESSING, SessionStatus.NEEDS_REVIEW)
        assert ok is True

    def test_processing_to_processing_failed(self):
        ok, reason = can_transition(SessionStatus.PROCESSING, SessionStatus.PROCESSING_FAILED)
        assert ok is True

    def test_processing_failed_to_processing(self):
        ok, reason = can_transition(SessionStatus.PROCESSING_FAILED, SessionStatus.PROCESSING)
        assert ok is True

    def test_needs_review_to_reviewing(self):
        ok, reason = can_transition(SessionStatus.NEEDS_REVIEW, SessionStatus.REVIEWING)
        assert ok is True

    def test_reviewing_to_approved(self):
        ok, reason = can_transition(SessionStatus.REVIEWING, SessionStatus.APPROVED)
        assert ok is True

    def test_approved_to_publishing(self):
        ok, reason = can_transition(SessionStatus.APPROVED, SessionStatus.PUBLISHING)
        assert ok is True

    def test_publishing_to_published(self):
        ok, reason = can_transition(SessionStatus.PUBLISHING, SessionStatus.PUBLISHED)
        assert ok is True

    def test_publishing_to_publish_failed(self):
        ok, reason = can_transition(SessionStatus.PUBLISHING, SessionStatus.PUBLISH_FAILED)
        assert ok is True

    def test_published_to_retracting(self):
        ok, reason = can_transition(SessionStatus.PUBLISHED, SessionStatus.RETRACTING)
        assert ok is True

    def test_retracting_to_retracted(self):
        ok, reason = can_transition(SessionStatus.RETRACTING, SessionStatus.RETRACTED)
        assert ok is True

    def test_self_transition(self):
        """Transitioning to the same state should be allowed."""
        ok, _ = can_transition(SessionStatus.IDLE, SessionStatus.IDLE)
        assert ok is True

    # ── Invalid transitions ────────────────────────────────────────

    def test_idle_to_capturing_without_consent(self):
        ok, reason = can_transition(SessionStatus.IDLE, SessionStatus.CAPTURING, consent_granted=False)
        assert ok is False
        assert "Consent" in reason

    def test_idle_to_processing_not_allowed(self):
        ok, reason = can_transition(SessionStatus.IDLE, SessionStatus.PROCESSING)
        assert ok is False

    def test_capturing_to_published_not_allowed(self):
        ok, reason = can_transition(SessionStatus.CAPTURING, SessionStatus.PUBLISHED)
        assert ok is False

    def test_published_to_idle_not_allowed(self):
        ok, reason = can_transition(SessionStatus.PUBLISHED, SessionStatus.IDLE)
        assert ok is False

    def test_retracted_is_terminal(self):
        ok, reason = can_transition(SessionStatus.RETRACTED, SessionStatus.IDLE)
        assert ok is False

    def test_cancelled_is_terminal(self):
        ok, reason = can_transition(SessionStatus.CANCELLED, SessionStatus.IDLE)
        assert ok is False

    def test_cancelled_to_anything(self):
        for target in SessionStatus:
            if target != SessionStatus.CANCELLED:
                ok, _ = can_transition(SessionStatus.CANCELLED, target)
                assert ok is False, f"CANCELLED should not transition to {target}"


# ══════════════════════════════════════════════════════════════════════
# Session API tests
# ══════════════════════════════════════════════════════════════════════

class TestSessionAPI:
    """Session CRUD and lifecycle through the API."""

    @pytest.mark.asyncio
    async def test_create_session(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "My Test Session",
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "idle"
        assert data["title"] == "My Test Session"
        assert data["consent_granted"] is False
        assert "id" in data

    @pytest.mark.asyncio
    async def test_list_sessions(self, async_client: AsyncClient, auth_headers: dict):
        # Create 3 sessions
        for i in range(3):
            resp = await async_client.post("/api/v1/sessions", json={
                "title": f"Session {i}",
            }, headers=auth_headers)
            assert resp.status_code == 201

        resp = await async_client.get("/api/v1/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 3
        assert len(data["sessions"]) >= 3

    @pytest.mark.asyncio
    async def test_get_session(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "Get Me",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        resp = await async_client.get(f"/api/v1/sessions/{sid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "Get Me"

    @pytest.mark.asyncio
    async def test_get_session_404(self, async_client: AsyncClient, auth_headers: dict):
        fake_id = str(uuid.uuid4())
        resp = await async_client.get(f"/api/v1/sessions/{fake_id}", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_grant_consent(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "Consent Test",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/consent",
            json={"consent": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["consent_granted"] is True

    @pytest.mark.asyncio
    async def test_revoke_consent(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "Revoke Consent",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        # Grant
        await async_client.patch(
            f"/api/v1/sessions/{sid}/consent",
            json={"consent": True},
            headers=auth_headers,
        )

        # Revoke
        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/consent",
            json={"consent": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["consent_granted"] is False

    @pytest.mark.asyncio
    async def test_status_to_capturing_without_consent_returns_403(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "No Consent",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/status",
            json={"status": "capturing"},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_status_to_capturing_with_consent_succeeds(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "With Consent",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        # Grant consent
        await async_client.patch(
            f"/api/v1/sessions/{sid}/consent",
            json={"consent": True},
            headers=auth_headers,
        )

        # Transition to capturing
        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/status",
            json={"status": "capturing"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "capturing"

    @pytest.mark.asyncio
    async def test_illegal_transition_returns_409(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "Illegal",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        # Try idle → published (not allowed)
        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/status",
            json={"status": "published"},
            headers=auth_headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_session(self, async_client: AsyncClient, auth_headers: dict):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "Cancel Me",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        resp = await async_client.post(
            f"/api/v1/sessions/{sid}/cancel",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cannot_cancel_published_session(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        """CANCELLED transition is only allowed from non-terminal states."""
        # We test with a cancelled session — cancelling again should fail
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "Already Cancelled",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        # Cancel once
        await async_client.post(f"/api/v1/sessions/{sid}/cancel", headers=auth_headers)

        # Cancel again
        resp = await async_client.post(f"/api/v1/sessions/{sid}/cancel", headers=auth_headers)
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_processing_without_audio_fails(
        self, async_client: AsyncClient, auth_headers: dict
    ):
        resp = await async_client.post("/api/v1/sessions", json={
            "title": "No Audio",
        }, headers=auth_headers)
        sid = resp.json()["id"]

        # Grant consent
        await async_client.patch(
            f"/api/v1/sessions/{sid}/consent",
            json={"consent": True},
            headers=auth_headers,
        )

        # Transition to capturing
        await async_client.patch(
            f"/api/v1/sessions/{sid}/status",
            json={"status": "capturing"},
            headers=auth_headers,
        )

        # Try processing without uploading audio
        resp = await async_client.patch(
            f"/api/v1/sessions/{sid}/status",
            json={"status": "processing"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "audio" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_unauthorized_cannot_access_sessions(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/sessions")
        assert resp.status_code == 401
