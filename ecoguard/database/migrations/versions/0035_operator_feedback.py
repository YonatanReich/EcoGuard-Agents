"""Operator feedback on handled incidents, and the reports written from it.

Revision ID: operator_feedback
Revises: isfiya_local_council
Create Date: 2026-10-05

The system had no ground truth. An incident closed when it went quiet, and
nothing recorded whether it had been real, whether the plan was any good, or
what the operator wished it had said. `operator_feedback` is that record: one
row per incident an operator marks handled, carrying a snapshot of what they
saw and, when they filled the survey in, what they thought of it. The same
table takes general feedback about the system, not tied to any incident.

`improvement_reports` is the improvement agent's output and its memory. Each
run reads the previous reports so it can say whether last time's suggestions
moved the numbers.

No foreign key to incidents: a feedback row is evidence about the system at
the moment of handling and must outlive whatever later happens to the incident.
The snapshot already holds everything the agent needs from it.
"""

from alembic import op

revision = "operator_feedback"
down_revision = "isfiya_local_council"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the feedback and report tables."""
    # Two kinds of row:
    #   handled  an operator finished with an incident. `incident_id` and
    #            `snapshot` are set; `feedback` is the survey, or NULL when they
    #            closed it without answering. The row is still written: how
    #            often the survey is skipped is itself something to report on.
    #   general  free-text feedback from the dashboard's Feedback button, about
    #            the system rather than one incident. `feedback` holds the text;
    #            there is no incident and no snapshot.
    op.execute(
        """
        CREATE TABLE operator_feedback (
          id            bigserial   PRIMARY KEY,
          kind          text        NOT NULL CHECK (kind IN ('handled', 'general')),
          incident_id   text,
          submitted_at  timestamptz NOT NULL,
          submitted_by  text        NOT NULL,
          code_version  text,
          feedback      jsonb,
          snapshot      jsonb,
          CHECK ((kind = 'handled') = (incident_id IS NOT NULL AND snapshot IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE INDEX operator_feedback_submitted_idx ON operator_feedback (submitted_at)"
    )

    op.execute(
        """
        CREATE TABLE improvement_reports (
          id              bigserial   PRIMARY KEY,
          created_at      timestamptz NOT NULL DEFAULT now(),
          window_start    timestamptz,
          window_end      timestamptz NOT NULL,
          feedback_count  integer     NOT NULL,
          model           text        NOT NULL,
          report          jsonb       NOT NULL
        )
        """
    )


def downgrade() -> None:
    """Drop both tables. Every recorded feedback row and report is lost."""
    op.execute("DROP TABLE IF EXISTS improvement_reports")
    op.execute("DROP INDEX IF EXISTS operator_feedback_submitted_idx")
    op.execute("DROP TABLE IF EXISTS operator_feedback")
