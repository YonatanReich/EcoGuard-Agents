"""observations (source, observed_at) index

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-10
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Everything that reads observations filters by source and a time *range*:
    # the collector asking which hours it is missing, the area summary taking
    # the newest reading per cell, the fire danger surface.
    #
    # Neither existing index serves that. observations_identity is
    # (source, cell_id, observed_at), so observed_at is the third column and a
    # range scan on it has to walk every cell_id first; the other index is on
    # ingested_at, which is the collector's cursor clock, not when the reading
    # was taken. The result was a sequential scan on a table that only grows.
    op.execute(
        "CREATE INDEX observations_source_observed_at_idx "
        "ON observations (source, observed_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS observations_source_observed_at_idx")
