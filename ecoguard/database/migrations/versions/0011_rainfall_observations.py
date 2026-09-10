"""Water Authority rain stations and numeric rainfall cache

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-11
"""

from alembic import op


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This metadata is returned together with every rain observation window.
    # source_owner_id is kept even if the shared owner catalog has not yet been
    # loaded; owner_id is repaired by later collector invocations.
    op.execute(
        """
        CREATE TABLE rain_stations (
          id                 bigserial PRIMARY KEY,
          source_station_id  bigint      NOT NULL,
          name_he            text,
          name_en            text,
          location           geography(Point, 4326) NOT NULL,
          source_owner_id    integer     NOT NULL,
          owner_id           bigint
            REFERENCES water_authority_station_owners(id) ON DELETE SET NULL,
          is_active          boolean     NOT NULL DEFAULT true,
          source_metadata    jsonb       NOT NULL DEFAULT '{}'::jsonb,
          synced_at          timestamptz NOT NULL,
          CONSTRAINT rain_stations_identity UNIQUE (source_station_id),
          CONSTRAINT rain_stations_has_name
            CHECK (name_he IS NOT NULL OR name_en IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE INDEX rain_stations_location_idx "
        "ON rain_stations USING GIST (location)"
    )
    op.execute(
        "CREATE INDEX rain_stations_owner_id_idx ON rain_stations (owner_id)"
    )
    op.execute(
        "CREATE INDEX rain_stations_source_owner_id_idx "
        "ON rain_stations (source_owner_id)"
    )

    # One immutable row per station and provider timestamp. Re-fetching the
    # rolling window every five minutes does not duplicate ten-minute samples.
    # The nullable FK preserves observations from source ids whose metadata is
    # temporarily absent, just as the hydrometric cache does.
    op.execute(
        """
        CREATE TABLE rainfall_observations (
          id                 bigserial PRIMARY KEY,
          source_station_id  bigint      NOT NULL,
          rain_station_id    bigint
            REFERENCES rain_stations(id) ON DELETE SET NULL,
          observed_at        timestamptz NOT NULL,
          rainfall_mm        double precision NOT NULL,
          source_payload     jsonb       NOT NULL,
          collected_at       timestamptz NOT NULL,
          CONSTRAINT rainfall_observations_identity
            UNIQUE (source_station_id, observed_at),
          CONSTRAINT rainfall_observations_nonnegative
            CHECK (rainfall_mm >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX rainfall_observations_station_time_idx "
        "ON rainfall_observations (rain_station_id, observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX rainfall_observations_source_station_time_idx "
        "ON rainfall_observations (source_station_id, observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX rainfall_observations_observed_at_idx "
        "ON rainfall_observations (observed_at DESC)"
    )

    # The provider also returns a current materialized summary per station.
    # Keep only its latest state: historical rolling totals are derivable from
    # rainfall_observations, while monthly/seasonal totals remain available.
    op.execute(
        """
        CREATE TABLE rainfall_accumulations (
          id                    bigserial PRIMARY KEY,
          source_station_id     bigint      NOT NULL,
          rain_station_id       bigint
            REFERENCES rain_stations(id) ON DELETE SET NULL,
          as_of                 timestamptz NOT NULL,
          rainfall_6h_mm        double precision,
          rainfall_12h_mm       double precision,
          rainfall_24h_mm       double precision,
          rainfall_month_mm     double precision,
          rainfall_season_mm    double precision,
          hourly_values         jsonb,
          source_payload        jsonb       NOT NULL,
          collected_at          timestamptz NOT NULL,
          CONSTRAINT rainfall_accumulations_identity
            UNIQUE (source_station_id),
          CONSTRAINT rainfall_accumulations_nonnegative CHECK (
            (rainfall_6h_mm IS NULL OR rainfall_6h_mm >= 0) AND
            (rainfall_12h_mm IS NULL OR rainfall_12h_mm >= 0) AND
            (rainfall_24h_mm IS NULL OR rainfall_24h_mm >= 0) AND
            (rainfall_month_mm IS NULL OR rainfall_month_mm >= 0) AND
            (rainfall_season_mm IS NULL OR rainfall_season_mm >= 0)
          ),
          CONSTRAINT rainfall_accumulations_hourly_object
            CHECK (hourly_values IS NULL OR jsonb_typeof(hourly_values) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX rainfall_accumulations_station_idx "
        "ON rainfall_accumulations (rain_station_id)"
    )
    op.execute(
        "CREATE INDEX rainfall_accumulations_as_of_idx "
        "ON rainfall_accumulations (as_of DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rainfall_accumulations")
    op.execute("DROP TABLE IF EXISTS rainfall_observations")
    op.execute("DROP TABLE IF EXISTS rain_stations")
