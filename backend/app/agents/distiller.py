"""Distiller agent — handles 'summarize' and 'extract_artifact' jobs.

Pipeline: transcript → LLM summary → LLM structured artifact → Artifact(s) in DB.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.schemas import ARTIFACT_SCHEMAS
from app.db.session import async_session_factory
from app.models.artifact import Artifact
from app.models.job import Job
from app.models.session import Session as SessionModel
from app.orchestrator.worker import register_handler
from app.providers.base import LLMProvider
from app.providers.openai_llm import OpenAILLMProvider

logger = logging.getLogger("distiller.agent")

_llm: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _llm
    if _llm is None:
        _llm = OpenAILLMProvider()
    return _llm


def set_llm(llm: LLMProvider) -> None:
    global _llm
    _llm = llm


SUMMARIZE_PROMPT = """You are an AI assistant that summarizes meeting transcripts.

Given the following transcript, produce:
1. A concise summary (2-3 sentences)
2. The suggested artifact type (one of: meeting_minutes, decision_record, faq_draft, sop_draft)
3. A title for the artifact

Transcript:
---
{transcript}
---

Respond as JSON with keys: summary, artifact_type, title."""

SUMMARIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "artifact_type": {
            "type": "string",
            "enum": ["meeting_minutes", "decision_record", "faq_draft", "sop_draft"],
        },
        "title": {"type": "string"},
    },
    "required": ["summary", "artifact_type", "title"],
    "additionalProperties": False,
}

EXTRACT_PROMPT = """You are an AI assistant that extracts structured information from meeting transcripts.

Transcript:
---
{transcript}
---

Produce a structured artifact of type '{artifact_type}' with the title '{title}'.

The output must conform to the required JSON schema. Be thorough and precise."""


@register_handler("summarize")
async def handle_summarize_job(session: AsyncSession, job: Job):
    """Summarize the transcript and determine artifact type."""
    logger.info(f"Handling summarize job {job.id}")
    llm = get_llm()

    transcript = await _get_transcript(job)
    prompt = SUMMARIZE_PROMPT.format(transcript=transcript)
    llm_result = await llm.complete(prompt, schema=SUMMARIZE_SCHEMA)

    job.output_payload = llm_result
    job.status = "completed"
    await session.commit()
    logger.info(f"Summarize job {job.id} completed → {llm_result.get('artifact_type')}")


@register_handler("extract_artifact")
async def handle_extract_artifact_job(session: AsyncSession, job: Job):
    """Extract structured artifact from transcript and create Artifact row."""
    logger.info(f"Handling extract_artifact job {job.id}")
    llm = get_llm()

    transcript = await _get_transcript(job)

    # Get summarize job output_payload for artifact type + title
    summarize_payload = await _get_summarize_result(job.session_id)
    artifact_type = summarize_payload.get("artifact_type", "meeting_minutes")
    title = summarize_payload.get("title", "Untitled")

    # Get the schema for this artifact type
    schema_class = ARTIFACT_SCHEMAS.get(artifact_type)
    if schema_class is None:
        raise ValueError(f"Unknown artifact_type: {artifact_type}")

    json_schema = schema_class.model_json_schema()

    prompt = EXTRACT_PROMPT.format(
        transcript=transcript,
        artifact_type=artifact_type,
        title=title,
    )
    content = await llm.complete(prompt, schema=json_schema)

    # Create Artifact in DB
    async with async_session_factory() as s:
        artifact = Artifact(
            session_id=job.session_id,
            job_id=job.id,
            artifact_type=artifact_type,
            title=title,
            content=content,
            summary=summarize_payload.get("summary", ""),
            status="pending_review",
        )
        s.add(artifact)

        # Update session status
        r = await s.execute(
            select(SessionModel).where(SessionModel.id == job.session_id)
        )
        sess = r.scalar_one_or_none()
        if sess:
            sess.status = "needs_review"

        await s.commit()

    job.output_payload = {"artifact_type": artifact_type, "title": title}
    job.status = "completed"
    await session.commit()
    logger.info(f"Extract artifact job {job.id} completed → {artifact_type}: {title}")


async def _get_transcript(job: Job) -> str:
    """Retrieve the transcript from the transcribe job's output_payload."""
    async with async_session_factory() as s:
        r = await s.execute(
            select(Job).where(
                Job.session_id == job.session_id,
                Job.job_type == "transcribe",
                Job.status == "completed",
            )
        )
        transcribe_job = r.scalar_one_or_none()
        if transcribe_job is None or transcribe_job.output_payload is None:
            raise ValueError("No completed transcribe job found for this session")
        return transcribe_job.output_payload.get("transcript", "")


async def _get_summarize_result(session_id) -> dict:
    """Retrieve the summarize job's output_payload."""
    async with async_session_factory() as s:
        r = await s.execute(
            select(Job).where(
                Job.session_id == session_id,
                Job.job_type == "summarize",
                Job.status == "completed",
            )
        )
        summarize_job = r.scalar_one_or_none()
        if summarize_job is None or summarize_job.output_payload is None:
            return {"artifact_type": "meeting_minutes", "title": "Untitled", "summary": ""}
        return summarize_job.output_payload
