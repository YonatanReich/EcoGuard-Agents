"""Store the operational baseline-flow class of hydrometric stations.

Revision ID: flood_operational_flow_regime
Revises: planning_failure_police
Create Date: 2026-10-01
"""

from alembic import op


revision = "flood_operational_flow_regime"
down_revision = "planning_failure_police"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the classification column; the reference-data loader populates it."""
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        ADD COLUMN operational_flow_regime text
        """
    )
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        ADD CONSTRAINT hydrometric_stations_operational_flow_regime_valid
        CHECK (
          operational_flow_regime IS NULL OR
          operational_flow_regime IN ('ephemeral', 'flowing_baseline')
        )
        """
    )


def downgrade() -> None:
    """Remove the operational station classification."""
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        DROP CONSTRAINT IF EXISTS hydrometric_stations_operational_flow_regime_valid
        """
    )
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        DROP COLUMN IF EXISTS operational_flow_regime
        """
    )
