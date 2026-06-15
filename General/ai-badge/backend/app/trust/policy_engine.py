"""Policy engine — enforces trust checks at key decision points."""

import logging
from typing import Optional

from app.models.session import Session as SessionModel
from app.trust.redlines import (
    RedlineResult,
    redline_consent_required,
    redline_no_capture_without_device,
    redline_audio_required_for_processing,
    redline_all_artifacts_approved_for_publish,
    redline_published_before_retract,
)

logger = logging.getLogger("trust.policy")


class PolicyViolation(Exception):
    def __init__(self, reason: str, level: str = "L1"):
        self.reason = reason
        self.level = level
        super().__init__(reason)


def check_consent(session: SessionModel) -> None:
    """Check consent is granted. Raises PolicyViolation on failure."""
    result = redline_consent_required(session)
    if not result.passed:
        raise PolicyViolation(result.reason, result.level)
    logger.info(f"check_consent passed for session {session.id}")


def check_capture(session: SessionModel) -> None:
    """Check device + consent for capturing. Raises PolicyViolation on failure."""
    check_consent(session)
    result = redline_no_capture_without_device(session)
    if not result.passed:
        raise PolicyViolation(result.reason, result.level)
    logger.info(f"check_capture passed for session {session.id}")


def check_reviewed(artifacts: list, session: SessionModel) -> None:
    """Check all artifacts for a session are approved.

    Raises PolicyViolation if any artifact is not approved.
    """
    result = redline_all_artifacts_approved_for_publish(artifacts)
    if not result.passed:
        raise PolicyViolation(result.reason, result.level)
    logger.info(f"check_reviewed passed for session {session.id}")


def check_publish(artifacts: list, session: SessionModel) -> None:
    """Check preconditions for publishing."""
    check_reviewed(artifacts, session)
    result = redline_audio_required_for_processing(session)
    if not result.passed:
        raise PolicyViolation(result.reason, result.level)
    logger.info(f"check_publish passed for session {session.id}")


def check_retract(session: SessionModel) -> None:
    """Check session can be retracted. Raises PolicyViolation on failure."""
    result = redline_published_before_retract(session)
    if not result.passed:
        raise PolicyViolation(result.reason, result.level)
    logger.info(f"check_retract passed for session {session.id}")
