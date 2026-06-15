"""Artifact API router — list, get, edit, review, publish."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.schemas import (
    ArtifactResponse,
    ArtifactListResponse,
    ArtifactUpdateRequest,
    ReviewRequest,
)
from app.artifacts.service import (
    approve_artifact,
    reject_artifact,
    request_publish,
)
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.artifact import Artifact
from app.models.user import User

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts", response_model=ArtifactListResponse)
async def list_artifacts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    """List all artifacts (Phase 1A: Owner sees all)."""
    count_q = select(func.count()).select_from(Artifact)
    total = (await db.execute(count_q)).scalar() or 0

    q = (
        select(Artifact)
        .order_by(Artifact.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    r = await db.execute(q)
    artifacts = r.scalars().all()

    return ArtifactListResponse(
        artifacts=[_to_response(a) for a in artifacts],
        total=total,
    )


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get artifact details."""
    artifact = await _get_artifact_or_404(db, artifact_id)
    return _to_response(artifact)


@router.patch("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def update_artifact(
    artifact_id: str,
    body: ArtifactUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit artifact content."""
    artifact = await _get_artifact_or_404(db, artifact_id)

    if body.title is not None:
        artifact.title = body.title
    if body.content is not None:
        artifact.content = body.content
    if body.summary is not None:
        artifact.summary = body.summary

    await db.flush()
    await db.refresh(artifact)
    return _to_response(artifact)


@router.patch("/artifacts/{artifact_id}/review", response_model=ArtifactResponse)
async def review_artifact(
    artifact_id: str,
    body: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject an artifact.

    - approve: artifact.status → approved. If all artifacts for the session
      are approved, session.status → approved.
    - reject: artifact.status → rejected. Creates a new extract_artifact job.
    """
    artifact = await _get_artifact_or_404(db, artifact_id)

    if body.action == "approve":
        await approve_artifact(db, artifact, current_user.id, body.comment)
    elif body.action == "reject":
        await reject_artifact(db, artifact, current_user.id, body.comment)

    await db.refresh(artifact)
    return _to_response(artifact)


@router.post("/artifacts/{artifact_id}/publish", response_model=ArtifactResponse)
async def publish_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a publish job for an approved artifact.

    Returns 403 if the artifact is not approved.
    """
    artifact = await _get_artifact_or_404(db, artifact_id)

    if artifact.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only approved artifacts can be published",
        )

    await request_publish(db, artifact, current_user.id)
    await db.flush()
    await db.refresh(artifact)
    return _to_response(artifact)


# ── Helpers ──────────────────────────────────────────────────────────

async def _get_artifact_or_404(db: AsyncSession, artifact_id: str) -> Artifact:
    try:
        aid = uuid.UUID(artifact_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    r = await db.execute(select(Artifact).where(Artifact.id == aid))
    artifact = r.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return artifact


def _to_response(a: Artifact) -> ArtifactResponse:
    return ArtifactResponse(
        id=str(a.id),
        session_id=str(a.session_id),
        job_id=str(a.job_id) if a.job_id else None,
        artifact_type=a.artifact_type,
        title=a.title,
        content=a.content,
        summary=a.summary,
        status=a.status,
        assigned_reviewer_id=str(a.assigned_reviewer_id) if a.assigned_reviewer_id else None,
        review_status=a.review_status,
        review_comment=a.review_comment,
        published_at=a.published_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )
