"""Artifact Pydantic schemas — structured output types + API request/response."""

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


# ── Structured output types ──────────────────────────────────────────

class MeetingMinutes(BaseModel):
    title: str = Field(description="Meeting title or topic")
    date: str = Field(description="Meeting date (ISO format)")
    participants: list[str] = Field(default_factory=list)
    summary: str = Field(description="Executive summary")
    key_points: list[str] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    action_items: list[dict] = Field(default_factory=list)


class DecisionRecord(BaseModel):
    title: str = Field(description="Decision title")
    context: str = Field(description="Background and context")
    decision: str = Field(description="The decision itself")
    rationale: str = Field(description="Why this decision was made")
    alternatives_considered: list[str] = Field(default_factory=list)
    implications: str = Field(default="")


class FAQDraft(BaseModel):
    title: str = Field(description="FAQ topic")
    questions: list[dict] = Field(default_factory=list)


class SOPDraft(BaseModel):
    title: str = Field(description="SOP title")
    purpose: str = Field(description="Purpose")
    scope: str = Field(default="")
    steps: list[dict] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


ARTIFACT_SCHEMAS: dict[str, type[BaseModel]] = {
    "meeting_minutes": MeetingMinutes,
    "decision_record": DecisionRecord,
    "faq_draft": FAQDraft,
    "sop_draft": SOPDraft,
}

# ── API schemas ──────────────────────────────────────────────────────

class ArtifactResponse(BaseModel):
    id: str
    session_id: str
    job_id: Optional[str] = None
    artifact_type: str
    title: Optional[str] = None
    content: dict
    summary: Optional[str] = None
    status: str
    assigned_reviewer_id: Optional[str] = None
    review_status: Optional[str] = None
    review_comment: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactResponse]
    total: int


class ArtifactUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[dict] = None
    summary: Optional[str] = None


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = ""
