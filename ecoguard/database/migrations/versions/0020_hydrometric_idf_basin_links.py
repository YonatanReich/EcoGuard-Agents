"""Link hydrometric stations to IDF rain stations in the same basin.

Revision ID: hydrometric_idf_basin_links
Revises: flood_station_threshold_status
Create Date: 2026-09-18
"""

from alembic import op


revision = "hydrometric_idf_basin_links"
down_revision = "flood_station_threshold_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE hydrometric_station_idf_links (
          hydrometric_station_id bigint NOT NULL
            REFERENCES hydrometric_stations(id) ON DELETE CASCADE,
          rain_station_id        bigint NOT NULL
            REFERENCES rain_stations(id) ON DELETE CASCADE,
          drainage_basin_id      bigint NOT NULL
            REFERENCES drainage_basins(id) ON DELETE CASCADE,
          distance_m             double precision NOT NULL,
          linked_at              timestamptz NOT NULL,
          CONSTRAINT hydrometric_station_idf_links_pk PRIMARY KEY (
            hydrometric_station_id, rain_station_id
          ),
          CONSTRAINT hydrometric_station_idf_links_distance_nonnegative
            CHECK (distance_m >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX hydrometric_station_idf_links_rain_station_idx "
        "ON hydrometric_station_idf_links (rain_station_id)"
    )
    op.execute(
        "CREATE INDEX hydrometric_station_idf_links_basin_idx "
        "ON hydrometric_station_idf_links (drainage_basin_id)"
    )
    op.execute(
        "CREATE INDEX hydrometric_station_idf_links_nearest_idx "
        "ON hydrometric_station_idf_links "
        "(hydrometric_station_id, distance_m)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hydrometric_station_idf_links")
