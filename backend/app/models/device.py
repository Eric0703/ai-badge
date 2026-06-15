"""Device model — Phase 1A users get virtual_phone_mic on registration."""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    device_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    device_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="virtual_phone_mic"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="devices")
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="device")
