"""Remove the unused source-map zoom level from hydrometric stations.

Revision ID: remove_hydrometric_map_zoom
Revises: flood_operational_flow_regime
Create Date: 2026-10-01
"""

from alembic import op


revision = "remove_hydrometric_map_zoom"
down_revision = "flood_operational_flow_regime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop source presentation metadata that EcoGuard does not use."""
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        DROP COLUMN IF EXISTS map_zoom_level
        """
    )


def downgrade() -> None:
    """Restore the nullable column; removed source values cannot be recovered."""
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        ADD COLUMN map_zoom_level integer
        """
    )
