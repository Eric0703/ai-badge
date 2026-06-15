"""Session model — capture/recording session.

States per DDL: idle | capturing | paused | processing | processing_failed |
needs_review | reviewing | approved | publishing | publish_failed | published |
retracting | retracted | cancelled

Consent is a boolean field consent_granted, not a status.
Audio metadata stored in audio_key (S3 key).
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Integer, Boolean, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="idle"
    )
    consent_granted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    audio_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    audio_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    audio_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Tombstone fields (for retract saga)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retracted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    retraction_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    device: Mapped["Device"] = relationship("Device", back_populates="sessions")
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="session")
