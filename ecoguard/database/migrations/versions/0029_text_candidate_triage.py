"""Durable text-candidate triage handoff state.

Revision ID: text_candidate_triage
Revises: weak_events
Create Date: 2026-09-22

Candidates remain queryable after triage because an older report may
corroborate a newer one. ``triaged_at`` says only that this candidate has
already had its own outcome persisted or handed to the Coordinator.
"""

from alembic import op


revision = "text_candidate_triage"
down_revision = "weak_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE text_candidates ADD COLUMN triaged_at timestamptz")
    op.execute(
        "CREATE INDEX text_candidates_pending_triage "
        "ON text_candidates (observed_at, id) WHERE triaged_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS text_candidates_pending_triage")
    op.execute("ALTER TABLE text_candidates DROP COLUMN triaged_at")
