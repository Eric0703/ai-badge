"""Unit tests — Trust module: 10 redlines, policy engine, sensitive check.

Tests:
- Each of the 10 redlines (L1 hard block + L2 warn)
- Policy engine check functions (raises PolicyViolation)
- Sensitive content detection (mock LLM)
- RedlineResult dataclass
"""

import uuid

import pytest

from app.trust.redlines import (
    RedlineResult,
    redline_consent_required,
    redline_no_capture_without_device,
    redline_audio_required_for_processing,
    redline_all_artifacts_approved_for_publish,
    redline_published_before_retract,
    redline_sensitive_content_check,
    redline_large_transcript,
    redline_no_participants_detected,
    redline_short_duration,
    redline_duplicate_session_title,
    REDLINES,
)
from app.trust.policy_engine import (
    PolicyViolation,
    check_consent,
    check_capture,
    check_reviewed,
    check_publish,
    check_retract,
)


# ── Helper: Mock session object ──────────────────────────────────────

class MockSession:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.uuid4())
        self.consent_granted = kwargs.get("consent_granted", False)
        self.device_id = kwargs.get("device_id", uuid.uuid4())
        self.audio_key = kwargs.get("audio_key", "test-audio.opus")
        self.status = kwargs.get("status", "idle")
        self.title = kwargs.get("title", "Test Session")


class MockArtifact:
    def __init__(self, status="approved"):
        self.status = status


# ══════════════════════════════════════════════════════════════════════
# Redlines: L1 Hard Constraints
# ══════════════════════════════════════════════════════════════════════

class TestL1Redlines:
    """L1 = hard block. Must pass for operations to proceed."""

    def test_consent_required_passes(self):
        session = MockSession(consent_granted=True)
        result = redline_consent_required(session)
        assert result.passed is True
        assert result.level == "L1"

    def test_consent_required_fails(self):
        session = MockSession(consent_granted=False)
        result = redline_consent_required(session)
        assert result.passed is False
        assert "Consent" in result.reason

    def test_no_capture_without_device_passes(self):
        session = MockSession(device_id=uuid.uuid4())
        result = redline_no_capture_without_device(session)
        assert result.passed is True

    def test_no_capture_without_device_fails(self):
        session = MockSession(device_id=None)
        result = redline_no_capture_without_device(session)
        assert result.passed is False

    def test_audio_required_for_processing_passes(self):
        session = MockSession(audio_key="file.opus")
        result = redline_audio_required_for_processing(session)
        assert result.passed is True

    def test_audio_required_for_processing_fails(self):
        session = MockSession(audio_key=None)
        result = redline_audio_required_for_processing(session)
        assert result.passed is False

    def test_all_artifacts_approved_passes(self):
        artifacts = [MockArtifact("approved"), MockArtifact("approved")]
        result = redline_all_artifacts_approved_for_publish(artifacts)
        assert result.passed is True

    def test_all_artifacts_approved_fails(self):
        artifacts = [MockArtifact("approved"), MockArtifact("pending_review")]
        result = redline_all_artifacts_approved_for_publish(artifacts)
        assert result.passed is False

    def test_published_before_retract_passes(self):
        session = MockSession(status="published")
        result = redline_published_before_retract(session)
        assert result.passed is True

    def test_published_before_retract_fails(self):
        session = MockSession(status="idle")
        result = redline_published_before_retract(session)
        assert result.passed is False


# ══════════════════════════════════════════════════════════════════════
# Redlines: L2 Soft Warnings
# ══════════════════════════════════════════════════════════════════════

class TestL2Redlines:
    """L2 = warn but don't block."""

    def test_sensitive_content_no_match(self):
        result = redline_sensitive_content_check("今天天气很好，适合开会讨论项目进展。")
        assert result.passed is True
        assert result.reason == ""

    def test_sensitive_content_found(self):
        result = redline_sensitive_content_check("请把密码改成123456")
        assert result.passed is True  # L2 always passes
        assert "密码" in result.reason

    def test_large_transcript_warns(self):
        big = "x" * 150_000
        result = redline_large_transcript(big)
        assert result.passed is True
        assert "Large" in result.reason

    def test_large_transcript_ok(self):
        small = "x" * 500
        result = redline_large_transcript(small)
        assert result.passed is True
        assert result.reason == ""

    def test_no_participants_warns(self):
        result = redline_no_participants_detected([])
        assert result.passed is True
        assert "No participants" in result.reason

    def test_with_participants_ok(self):
        result = redline_no_participants_detected(["张三", "李四"])
        assert result.passed is True
        assert result.reason == ""

    def test_short_duration_warns(self):
        result = redline_short_duration(3.0)
        assert result.passed is True
        assert "short" in result.reason.lower()

    def test_short_duration_none_ok(self):
        result = redline_short_duration(None)
        assert result.passed is True

    def test_duplicate_session_title_warns(self):
        result = redline_duplicate_session_title(None)
        assert result.passed is True
        assert "no title" in result.reason.lower()

    def test_session_title_ok(self):
        result = redline_duplicate_session_title("My Session")
        assert result.passed is True
        assert result.reason == ""


# ══════════════════════════════════════════════════════════════════════
# RedlineResult Dataclass
# ══════════════════════════════════════════════════════════════════════

class TestRedlineResult:
    def test_redline_result_creation(self):
        r = RedlineResult(passed=True, reason="", level="L1")
        assert r.passed is True
        assert r.reason == ""
        assert r.level == "L1"

    def test_count_is_10(self):
        assert len(REDLINES) == 10, f"Expected 10 redlines, got {len(REDLINES)}"


# ══════════════════════════════════════════════════════════════════════
# Policy Engine
# ══════════════════════════════════════════════════════════════════════

class TestPolicyEngine:
    """Policy engine raises PolicyViolation on failure."""

    def test_check_consent_passes(self):
        session = MockSession(consent_granted=True)
        check_consent(session)  # Should not raise

    def test_check_consent_fails(self):
        session = MockSession(consent_granted=False)
        with pytest.raises(PolicyViolation) as exc:
            check_consent(session)
        assert exc.value.level == "L1"

    def test_check_capture_passes(self):
        session = MockSession(consent_granted=True, device_id=uuid.uuid4())
        check_capture(session)  # Should not raise

    def test_check_capture_fails_no_consent(self):
        session = MockSession(consent_granted=False, device_id=uuid.uuid4())
        with pytest.raises(PolicyViolation):
            check_capture(session)

    def test_check_capture_fails_no_device(self):
        session = MockSession(consent_granted=True, device_id=None)
        with pytest.raises(PolicyViolation):
            check_capture(session)

    def test_check_reviewed_passes(self):
        artifacts = [MockArtifact("approved"), MockArtifact("approved")]
        session = MockSession()
        check_reviewed(artifacts, session)  # Should not raise

    def test_check_reviewed_fails(self):
        artifacts = [MockArtifact("approved"), MockArtifact("rejected")]
        session = MockSession()
        with pytest.raises(PolicyViolation):
            check_reviewed(artifacts, session)

    def test_check_publish_passes(self):
        artifacts = [MockArtifact("approved")]
        session = MockSession(audio_key="audio.opus")
        check_publish(artifacts, session)  # Should not raise

    def test_check_retract_passes(self):
        session = MockSession(status="published")
        check_retract(session)  # Should not raise

    def test_check_retract_fails(self):
        session = MockSession(status="idle")
        with pytest.raises(PolicyViolation):
            check_retract(session)

    def test_policy_violation_is_exception(self):
        e = PolicyViolation("test reason", "L1")
        with pytest.raises(PolicyViolation):
            raise e
