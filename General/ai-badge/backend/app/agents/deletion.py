"""Deletion agent — handles deletion_jobs for Saga retraction.

Processes: delete_artifact_rows, delete_local_audio, delete_feishu_docs
Feishu stub failures do NOT block retraction.
"""

import logging
import os

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.models.artifact import Artifact
from app.models.deletion_job import DeletionJob
from app.models.session import Session as SessionModel
from app.orchestrator.worker import register_handler

logger = logging.getLogger("deletion.agent")


@register_handler("delete_artifact_rows")
async def handle_delete_artifacts(session: AsyncSession, job: DeletionJob):
    """Hard-delete all artifacts for a session."""
    logger.info(f"Deleting artifacts for session {job.session_id}")
    async with async_session_factory() as s:
        await s.execute(
            delete(Artifact).where(Artifact.session_id == job.session_id)
        )
        await s.commit()
    job.status = "completed"
    await session.commit()


@register_handler("delete_local_audio")
async def handle_delete_audio(session: AsyncSession, job: DeletionJob):
    """Delete the local audio file."""
    audio_key = (job.cascade_targets or {}).get("audio_key")
    if audio_key:
        path = os.path.join(settings.audio_storage_path, audio_key)
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Deleted audio file: {path}")
    job.status = "completed"
    await session.commit()


@register_handler("delete_feishu_docs")
async def handle_delete_feishu(session: AsyncSession, job: DeletionJob):
    """Feishu stub — always succeeds (failure does NOT block retraction)."""
    logger.info(f"Feishu stub: would delete docs for session {job.session_id}")
    # Stub: no actual Feishu API call
    job.status = "completed"
    await session.commit()
