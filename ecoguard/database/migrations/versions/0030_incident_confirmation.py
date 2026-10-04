"""Operator confirmation on an incident.

Confirmation used to be implicit and unrecordable: an incident either carried
instrument evidence or it did not, and there was nowhere to put "a person
checked this and it is real". These two columns are the second way an incident
becomes confirmed.

Nullable, and expected to stay null on most rows: an incident that a satellite
or a gauge confirms never needs them, because instrument evidence is read from
the signals themselves and cannot go stale the way a stored flag can.
"""

from alembic import op

revision = "incident_confirmation"
down_revision = "planning_failure_police"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the operator-confirmation columns."""
    op.execute("ALTER TABLE incidents ADD COLUMN confirmed_at timestamptz")
    op.execute("ALTER TABLE incidents ADD COLUMN confirmed_by text")


def downgrade() -> None:
    """Drop them again. Any operator confirmations recorded are lost."""
    op.execute("ALTER TABLE incidents DROP COLUMN confirmed_by")
    op.execute("ALTER TABLE incidents DROP COLUMN confirmed_at")
