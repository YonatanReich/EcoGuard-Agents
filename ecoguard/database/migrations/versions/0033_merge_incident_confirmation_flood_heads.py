"""Merge incident confirmation with the hydrometric-station changes.

Revision ID: incident_flood_merge
Revises: incident_confirmation, remove_hydrometric_map_zoom
Create Date: 2026-10-04
"""


revision = "incident_flood_merge"
down_revision = ("incident_confirmation", "remove_hydrometric_map_zoom")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the two already-defined migration branches."""


def downgrade() -> None:
    """Split the history back into its two parent branches."""
