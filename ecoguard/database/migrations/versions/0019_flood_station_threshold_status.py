"""Make hydrometric-station detector eligibility explicit.

Revision ID: flood_station_threshold_status
Revises: flood_station_topology
Create Date: 2026-09-18
"""

from alembic import op


revision = "flood_station_threshold_status"
down_revision = "flood_station_topology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        ADD COLUMN flow_threshold_status text
        """
    )
    op.execute(
        """
        UPDATE hydrometric_stations
        SET flow_threshold_status = CASE
          WHEN flow_threshold_2y_m3s IS NULL
           AND flow_threshold_5y_m3s IS NULL
           AND flow_threshold_10y_m3s IS NULL
           AND flow_threshold_20y_m3s IS NULL
           AND flow_threshold_50y_m3s IS NULL
           AND flow_threshold_100y_m3s IS NULL
            THEN 'missing_thresholds'
          WHEN flow_threshold_2y_m3s IS NOT NULL
           AND flow_threshold_5y_m3s IS NOT NULL
           AND flow_threshold_10y_m3s IS NOT NULL
           AND flow_threshold_20y_m3s IS NOT NULL
           AND flow_threshold_50y_m3s IS NOT NULL
           AND flow_threshold_100y_m3s IS NOT NULL
            THEN 'complete_thresholds'
          ELSE 'partial_thresholds'
        END
        """
    )
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        ALTER COLUMN flow_threshold_status SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        ADD CONSTRAINT hydrometric_stations_flow_threshold_status_valid
        CHECK (flow_threshold_status IN (
          'complete_thresholds', 'missing_thresholds', 'partial_thresholds'
        ))
        """
    )
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        ADD CONSTRAINT hydrometric_stations_flow_threshold_status_consistent
        CHECK (
          (
            flow_threshold_status = 'missing_thresholds'
            AND flow_threshold_2y_m3s IS NULL
            AND flow_threshold_5y_m3s IS NULL
            AND flow_threshold_10y_m3s IS NULL
            AND flow_threshold_20y_m3s IS NULL
            AND flow_threshold_50y_m3s IS NULL
            AND flow_threshold_100y_m3s IS NULL
          ) OR (
            flow_threshold_status = 'complete_thresholds'
            AND flow_threshold_2y_m3s IS NOT NULL
            AND flow_threshold_5y_m3s IS NOT NULL
            AND flow_threshold_10y_m3s IS NOT NULL
            AND flow_threshold_20y_m3s IS NOT NULL
            AND flow_threshold_50y_m3s IS NOT NULL
            AND flow_threshold_100y_m3s IS NOT NULL
          ) OR (
            flow_threshold_status = 'partial_thresholds'
            AND NOT (
              flow_threshold_2y_m3s IS NULL
              AND flow_threshold_5y_m3s IS NULL
              AND flow_threshold_10y_m3s IS NULL
              AND flow_threshold_20y_m3s IS NULL
              AND flow_threshold_50y_m3s IS NULL
              AND flow_threshold_100y_m3s IS NULL
            )
            AND NOT (
              flow_threshold_2y_m3s IS NOT NULL
              AND flow_threshold_5y_m3s IS NOT NULL
              AND flow_threshold_10y_m3s IS NOT NULL
              AND flow_threshold_20y_m3s IS NOT NULL
              AND flow_threshold_50y_m3s IS NOT NULL
              AND flow_threshold_100y_m3s IS NOT NULL
            )
          )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        DROP CONSTRAINT IF EXISTS hydrometric_stations_flow_threshold_status_consistent
        """
    )
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        DROP CONSTRAINT IF EXISTS hydrometric_stations_flow_threshold_status_valid
        """
    )
    op.execute(
        """
        ALTER TABLE hydrometric_stations
        DROP COLUMN IF EXISTS flow_threshold_status
        """
    )
