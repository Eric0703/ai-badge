"""Audit service — INSERT-only audit log writer.

Audit logs are immutable. Only create() is exposed;
no update() or delete() methods exist.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger("audit.service")


async def audit_write(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
    session_id: Optional[uuid.UUID] = None,
    artifact_id: Optional[uuid.UUID] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> AuditLog:
    """Create an audit log entry. INSERT only — no update/delete."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        session_id=session_id,
        artifact_id=artifact_id,
        details=details,
        ip_address=ip_address,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.flush()
    logger.info(f"Audit: {action} on {resource_type}/{resource_id}")
    return entry
