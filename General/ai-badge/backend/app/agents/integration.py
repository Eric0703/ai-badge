"""Integration agent — handles 'publish' jobs (Feishu stub for Phase 1A)."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.service import mark_published
from app.db.session import async_session_factory
from app.models.artifact import Artifact
from app.models.job import Job
from app.orchestrator.worker import register_handler

logger = logging.getLogger("integration.agent")


@register_handler("publish")
async def handle_publish_job(session: AsyncSession, job: Job):
    """Publish an artifact — Feishu stub for Phase 1A.

    Generates a fake feishu_doc_id and marks the artifact as published.
    Uses the service layer for state transitions (artifacts/service.py).
    """
    logger.info(f"Handling publish job {job.id}")

    payload = job.input_payload or {}
    artifact_id = payload.get("artifact_id")

    if not artifact_id:
        raise ValueError("publish job missing artifact_id in input_payload")

    # Feishu stub: generate fake doc ID
    feishu_doc_id = f"feishu-doc-{artifact_id[:8]}"

    # Worker boundary: new session is allowed for independent background work
    async with async_session_factory() as s:
        r = await s.execute(
            select(Artifact).where(Artifact.id == artifact_id)
        )
        artifact = r.scalar_one_or_none()
        if artifact:
            await mark_published(s, artifact, feishu_doc_id=feishu_doc_id)
        await s.commit()

    job.output_payload = {"feishu_doc_id": feishu_doc_id}
    job.status = "completed"
    await session.commit()

    logger.info(f"Publish job {job.id} completed → {feishu_doc_id}")
