"""002_workflow_events_nullable_job_id

Expand workflow_events to support job, session, and artifact level events.

Changes:
- job_id → nullable (non-job events use session_id/artifact_id/resource_type instead)
- Add session_id, artifact_id, resource_type, resource_id columns
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Make job_id nullable ──────────────────────────────────────
    op.alter_column("workflow_events", "job_id", existing_type=postgresql.UUID(), nullable=True)

    # ── 2. Add resource tracking columns ─────────────────────────────
    op.add_column("workflow_events", sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("workflow_events", sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("workflow_events", sa.Column("resource_type", sa.String(32), nullable=False, server_default="job"))
    op.add_column("workflow_events", sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True))

    # ── 3. Indexes for new lookup paths ──────────────────────────────
    op.create_index("ix_workflow_events_session_id", "workflow_events", ["session_id"])
    op.create_index("ix_workflow_events_artifact_id", "workflow_events", ["artifact_id"])
    op.create_index("ix_workflow_events_resource_type", "workflow_events", ["resource_type"])

    # ── 4. Backfill existing rows ────────────────────────────────────
    op.execute("UPDATE workflow_events SET resource_type = 'job' WHERE job_id IS NOT NULL")
    op.execute("UPDATE workflow_events SET resource_id = job_id WHERE job_id IS NOT NULL")


def downgrade() -> None:
    op.drop_index("ix_workflow_events_resource_type")
    op.drop_index("ix_workflow_events_artifact_id")
    op.drop_index("ix_workflow_events_session_id")
    op.drop_column("workflow_events", "resource_id")
    op.drop_column("workflow_events", "resource_type")
    op.drop_column("workflow_events", "artifact_id")
    op.drop_column("workflow_events", "session_id")
    op.alter_column("workflow_events", "job_id", existing_type=postgresql.UUID(), nullable=False)
