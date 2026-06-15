"""Audit log API router — read-only logs endpoint."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.audit_log import AuditLog
from pydantic import BaseModel

router = APIRouter(tags=["audit"])


class AuditLogResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    session_id: Optional[str] = None
    artifact_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: str


class AuditLogListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    limit: int = 50,
    offset: int = 0,
):
    """List audit logs with pagination and optional session_id filter."""
    base_q = select(AuditLog)

    if session_id:
        base_q = base_q.where(AuditLog.session_id == session_id)

    count_q = select(func.count()).select_from(AuditLog)
    if session_id:
        count_q = count_q.where(AuditLog.session_id == session_id)

    total = (await db.execute(count_q)).scalar() or 0

    q = (
        base_q
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    r = await db.execute(q)
    logs = r.scalars().all()

    return AuditLogListResponse(
        logs=[
            AuditLogResponse(
                id=str(log.id),
                user_id=str(log.user_id) if log.user_id else None,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=str(log.resource_id) if log.resource_id else None,
                session_id=str(log.session_id) if log.session_id else None,
                artifact_id=str(log.artifact_id) if log.artifact_id else None,
                details=log.details,
                ip_address=log.ip_address,
                created_at=log.created_at.isoformat() if log.created_at else "",
            )
            for log in logs
        ],
        total=total,
    )
