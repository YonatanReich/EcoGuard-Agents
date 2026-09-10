"""Water Authority hydrometric observations cache

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-11
"""

from alembic import op


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # source_station_id remains mandatory even when the current station catalog
    # no longer contains an older station. This lets the cache preserve every
    # provider observation without fabricating station metadata. The nullable
    # FK is filled when a matching catalog row exists.
    op.execute(
        """
        CREATE TABLE hydrometric_observations (
          id                       bigserial PRIMARY KEY,
          source_station_id        integer     NOT NULL,
          hydrometric_station_id   bigint
            REFERENCES hydrometric_stations(id) ON DELETE SET NULL,
          observed_at              timestamptz NOT NULL,
          discharge_m3s            double precision,
          water_height_m           double precision,
          source_payload           jsonb       NOT NULL,
          collected_at             timestamptz NOT NULL,
          CONSTRAINT hydrometric_observations_identity
            UNIQUE (source_station_id, observed_at),
          CONSTRAINT hydrometric_observations_has_measurement
            CHECK (discharge_m3s IS NOT NULL OR water_height_m IS NOT NULL),
          CONSTRAINT hydrometric_observations_discharge_nonnegative
            CHECK (discharge_m3s IS NULL OR discharge_m3s >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX hydrometric_observations_station_time_idx "
        "ON hydrometric_observations (hydrometric_station_id, observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX hydrometric_observations_source_station_time_idx "
        "ON hydrometric_observations (source_station_id, observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX hydrometric_observations_observed_at_idx "
        "ON hydrometric_observations (observed_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hydrometric_observations")
