"""Redlines — 10 hard constraints for the AI Badge system.

Each redline is a function that returns (passed: bool, reason: str).
L1 = hard block, L2 = warn but allow.
"""

from dataclasses import dataclass


@dataclass
class RedlineResult:
    passed: bool
    reason: str
    level: str  # "L1" = hard block, "L2" = warn


# ── L1 Hard Constraints ──────────────────────────────────────────────

def redline_consent_required(session) -> RedlineResult:
    """Recording requires explicit user consent."""
    if not session.consent_granted:
        return RedlineResult(False, "Consent not granted", "L1")
    return RedlineResult(True, "", "L1")


def redline_no_capture_without_device(session) -> RedlineResult:
    """Capturing requires a device."""
    if session.device_id is None:
        return RedlineResult(False, "No device assigned to session", "L1")
    return RedlineResult(True, "", "L1")


def redline_audio_required_for_processing(session) -> RedlineResult:
    """Cannot process without audio data."""
    if session.audio_key is None:
        return RedlineResult(False, "No audio file uploaded", "L1")
    return RedlineResult(True, "", "L1")


def redline_all_artifacts_approved_for_publish(artifacts) -> RedlineResult:
    """All artifacts must be approved before publishing."""
    unapproved = [a for a in artifacts if a.status != "approved"]
    if unapproved:
        return RedlineResult(
            False,
            f"{len(unapproved)} artifact(s) not yet approved",
            "L1",
        )
    return RedlineResult(True, "", "L1")


def redline_published_before_retract(session) -> RedlineResult:
    """Only published sessions can be retracted."""
    if session.status != "published":
        return RedlineResult(
            False, f"Session status is '{session.status}', not 'published'", "L1"
        )
    return RedlineResult(True, "", "L1")


# ── L2 Soft Warnings ─────────────────────────────────────────────────

def redline_sensitive_content_check(transcript: str) -> RedlineResult:
    """Warn if transcript appears to contain sensitive content (keyword heuristic)."""
    sensitive_keywords = [
        "password", "secret", "token", "private key",
        "身份证", "银行卡", "密码",
    ]
    found = [kw for kw in sensitive_keywords if kw.lower() in transcript.lower()]
    if found:
        return RedlineResult(
            True,  # Passes — only warns
            f"Potential sensitive content detected: {', '.join(found)}",
            "L2",
        )
    return RedlineResult(True, "", "L2")


def redline_large_transcript(transcript: str) -> RedlineResult:
    """Warn if transcript is unusually large."""
    if len(transcript) > 100_000:
        return RedlineResult(
            True,
            f"Large transcript ({len(transcript)} chars), may impact quality",
            "L2",
        )
    return RedlineResult(True, "", "L2")


def redline_no_participants_detected(participants: list) -> RedlineResult:
    """Warn if no participants identified."""
    if not participants:
        return RedlineResult(True, "No participants detected in transcript", "L2")
    return RedlineResult(True, "", "L2")


def redline_short_duration(duration_seconds: float | None) -> RedlineResult:
    """Warn if recording is very short."""
    if duration_seconds is not None and duration_seconds < 5:
        return RedlineResult(
            True, f"Very short recording ({duration_seconds:.1f}s)", "L2"
        )
    return RedlineResult(True, "", "L2")


def redline_duplicate_session_title(title: str | None) -> RedlineResult:
    """Warn if session title is empty."""
    if not title:
        return RedlineResult(True, "Session has no title", "L2")
    return RedlineResult(True, "", "L2")


# ── Registry ─────────────────────────────────────────────────────────

REDLINES = [
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
]
