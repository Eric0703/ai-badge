"""Session API router."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import audit_write
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.deletion_job import DeletionJob
from app.models.session import Session as SessionModel
from app.models.user import User
from app.orchestrator.service import create_jobs_for_session
from app.models.device import Device
from app.sessions.schemas import (
    SessionCreateRequest,
    SessionUpdateStatusRequest,
    SessionConsentRequest,
    SessionResponse,
    SessionListResponse,
)
from app.sessions.service import SessionStatus, can_transition
from app.storage.local import LocalStorage
from app.trust.policy_engine import check_retract as policy_check_retract

router = APIRouter(tags=["sessions"])
_storage: LocalStorage | None = None


def _get_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage()
    return _storage


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new capture session (initial status: idle).

    If device_id is not provided, auto-resolves to the user's virtual_phone_mic device.
    """
    device_id = uuid.UUID(body.device_id) if body.device_id else None
    if device_id is None:
        # Auto-resolve: use the user's virtual_phone_mic device
        r = await db.execute(
            select(Device).where(
                Device.user_id == current_user.id,
                Device.device_type == "virtual_phone_mic",
            ).limit(1)
        )
        virtual_device = r.scalar_one_or_none()
        if virtual_device:
            device_id = virtual_device.id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No device_id provided and no virtual_phone_mic found for user",
            )

    session = SessionModel(
        user_id=current_user.id,
        device_id=device_id,
        title=body.title,
        status=SessionStatus.IDLE.value,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return _to_response(session)


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    """List sessions for the current user."""
    count_q = select(func.count()).select_from(SessionModel).where(
        SessionModel.user_id == current_user.id
    )
    total = (await db.execute(count_q)).scalar() or 0

    q = (
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(q)
    sessions = result.scalars().all()

    return SessionListResponse(
        sessions=[_to_response(s) for s in sessions],
        total=total,
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a session by ID."""
    session = await _get_session_or_404(db, session_id, current_user.id)
    return _to_response(session)


@router.patch("/sessions/{session_id}/consent", response_model=SessionResponse)
async def update_consent(
    session_id: str,
    body: SessionConsentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grant or revoke consent for a session.

    Granting: validate session is in a valid state, then set consent_granted=True.
    Revoking: reject if session is in a terminal state.

    The policy check (redline_consent_required) is NOT called here — it checks
    consent_granted flag, which is set *during* this request.  Policy checks
    run at action points (capture, publish) where consent must already be granted.
    """
    session = await _get_session_or_404(db, session_id, current_user.id)

    if body.consent:
        # Grant: validate session state allows consent
        current = SessionStatus(session.status)
        if current in (
            SessionStatus.PUBLISHED,
            SessionStatus.RETRACTED,
            SessionStatus.RETRACTING,
            SessionStatus.CANCELLED,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot grant consent in status {current.value}",
            )
        session.consent_granted = True
    else:
        # Revoke: reject terminal states
        current = SessionStatus(session.status)
        if current in (
            SessionStatus.PUBLISHED,
            SessionStatus.RETRACTED,
            SessionStatus.RETRACTING,
            SessionStatus.CANCELLED,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot revoke consent from terminal state",
            )
        session.consent_granted = False

    await db.flush()

    # Audit log
    await audit_write(
        db,
        action="consent_granted" if body.consent else "consent_revoked",
        resource_type="session",
        resource_id=session.id,
        user_id=current_user.id,
        session_id=session.id,
    )
    await db.refresh(session)
    return _to_response(session)


@router.patch("/sessions/{session_id}/status", response_model=SessionResponse)
async def update_session_status(
    session_id: str,
    body: SessionUpdateStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update session status (state machine)."""
    session = await _get_session_or_404(db, session_id, current_user.id)

    try:
        target = SessionStatus(body.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {body.status}",
        )

    current = SessionStatus(session.status)
    allowed, reason = can_transition(current, target, consent_granted=session.consent_granted)

    if not allowed:
        if target == SessionStatus.CAPTURING and not session.consent_granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=reason,
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)

    session.status = target.value
    await db.flush()

    if target == SessionStatus.PROCESSING:
        if session.audio_key is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio must be uploaded before starting processing",
            )
        await create_jobs_for_session(db, session.id)
        await db.flush()

    await db.refresh(session)
    return _to_response(session)


@router.post("/sessions/{session_id}/audio", response_model=SessionResponse)
async def upload_audio(
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an audio file for a session."""
    session = await _get_session_or_404(db, session_id, current_user.id)

    content = await file.read()
    audio_format = _get_audio_format(file.filename, file.content_type)
    file_key = f"{uuid.uuid4()}.{audio_format}"
    await _get_storage().save(file_key, content)

    session.audio_key = file_key
    session.audio_format = audio_format
    session.audio_size_bytes = len(content)

    await db.flush()
    await db.refresh(session)
    return _to_response(session)


@router.post("/sessions/{session_id}/cancel", response_model=SessionResponse)
async def cancel_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a session."""
    session = await _get_session_or_404(db, session_id, current_user.id)
    current = SessionStatus(session.status)

    allowed, reason = can_transition(current, SessionStatus.CANCELLED)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)

    session.status = SessionStatus.CANCELLED.value
    await db.flush()
    await db.refresh(session)
    return _to_response(session)


@router.post("/sessions/{session_id}/retract", response_model=SessionResponse)
async def retract_session_endpoint(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retract a published session via Saga + deletion_jobs."""
    session = await _get_session_or_404(db, session_id, current_user.id)

    # T9: Policy check
    policy_check_retract(session)

    # T11: Saga via service
    from app.sessions.service import retract_session
    await retract_session(db, session.id, current_user.id)

    # T9: Audit log
    await audit_write(
        db,
        action="retract_initiated",
        resource_type="session",
        resource_id=session.id,
        user_id=current_user.id,
        session_id=session.id,
    )

    await db.refresh(session)
    return _to_response(session)


# ── Helpers ──────────────────────────────────────────────────────────


async def _get_session_or_404(
    db: AsyncSession, session_id: str, user_id: uuid.UUID
) -> SessionModel:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    result = await db.execute(
        select(SessionModel).where(
            SessionModel.id == sid, SessionModel.user_id == user_id
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _to_response(s: SessionModel) -> SessionResponse:
    return SessionResponse(
        id=str(s.id),
        user_id=str(s.user_id),
        device_id=str(s.device_id) if s.device_id else None,
        title=s.title,
        status=s.status,
        consent_granted=s.consent_granted,
        audio_key=s.audio_key,
        audio_format=s.audio_format,
        audio_size_bytes=s.audio_size_bytes,
        duration_seconds=s.duration_seconds,
        metadata_json=s.metadata_json,
        started_at=s.started_at,
        ended_at=s.ended_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _get_audio_format(filename: str | None, content_type: str | None) -> str:
    if filename:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in ("opus", "wav", "mp3", "m4a", "ogg", "webm"):
            return ext
    if content_type:
        mapping = {
            "audio/opus": "opus",
            "audio/wav": "wav",
            "audio/mpeg": "mp3",
            "audio/mp4": "m4a",
            "audio/ogg": "ogg",
            "audio/webm": "webm",
        }
        return mapping.get(content_type, "opus")
    return "opus"
