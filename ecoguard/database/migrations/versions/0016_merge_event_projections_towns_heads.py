"""Join event projections with the authoritative towns migration history.

Revision ID: event_projections_towns_merge
Revises: event_projections, towns_air_pollution_merge
Create Date: 2026-09-18

The Air Pollution branch and main each merged earlier shared ancestors while
developing independently. This no-op revision records their final convergence;
the towns table remains the only settlement schema.
"""

revision = "event_projections_towns_merge"
down_revision = ("event_projections", "towns_air_pollution_merge")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to do: this revision only joins migration histories."""


def downgrade() -> None:
    """Nothing to undo."""
