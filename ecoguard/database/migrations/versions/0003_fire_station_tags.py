"""fire_stations.tags

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-10
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add fire_stations.tags."""
    # What OpenStreetMap knows about the station beyond where it is: phone,
    # website, opening_hours, operator, street address. Only a handful of
    # stations carry each, which is exactly why this is a jsonb rather than
    # five mostly-NULL columns.
    op.execute("ALTER TABLE fire_stations ADD COLUMN tags jsonb NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    """Remove fire_stations.tags."""
    op.execute("ALTER TABLE fire_stations DROP COLUMN IF EXISTS tags")
