"""Session Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    title: Optional[str] = None
    device_id: Optional[str] = None


class SessionUpdateStatusRequest(BaseModel):
    status: str


class SessionConsentRequest(BaseModel):
    consent: bool


class SessionResponse(BaseModel):
    id: str
    user_id: str
    device_id: Optional[str] = None
    title: Optional[str] = None
    status: str
    consent_granted: bool
    audio_key: Optional[str] = None
    audio_format: Optional[str] = None
    audio_size_bytes: Optional[int] = None
    duration_seconds: Optional[float] = None
    metadata_json: Optional[dict] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int
