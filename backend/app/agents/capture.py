"""Capture agent — handles 'transcribe' jobs dispatched by the Worker."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.capture.service import transcribe_audio
from app.db.session import async_session_factory
from app.models.job import Job
from app.models.session import Session as SessionModel
from app.orchestrator.worker import register_handler

logger = logging.getLogger("capture.agent")


@register_handler("transcribe")
async def handle_transcribe_job(session: AsyncSession, job: Job):
    """Worker handler for transcribe jobs.

    Reads the session's audio_key, transcribes via Whisper,
    and stores the TranscriptResult in job.output_payload.
    """
    logger.info(f"Handling transcribe job {job.id}")

    session_id = job.session_id
    if session_id is None:
        raise ValueError("transcribe job has no session_id")

    async with async_session_factory() as s:
        r = await s.execute(
            select(SessionModel).where(SessionModel.id == session_id)
        )
        session_obj = r.scalar_one_or_none()
        if session_obj is None:
            raise ValueError(f"Session {session_id} not found")
        if session_obj.audio_key is None:
            raise ValueError(f"Session {session_id} has no audio_key")
        audio_key = session_obj.audio_key

    transcript_result = await transcribe_audio(audio_key)

    job.output_payload = {
        "transcript": transcript_result.transcript,
        "segments": transcript_result.segments,
        "language": transcript_result.language,
    }
    job.status = "completed"
    await session.commit()

    logger.info(f"Transcribe job {job.id} completed ({len(transcript_result.transcript)} chars)")
