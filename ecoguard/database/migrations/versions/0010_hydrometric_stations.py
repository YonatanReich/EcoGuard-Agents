"""Hydrometric stations, owners and associated rain-station links

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-10
"""

from alembic import op


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The station endpoint returns owners as a separate object keyed by its own
    # source id. Keep that normalization in the database instead of repeating
    # the owner name and code on every station row.
    op.execute(
        """
        CREATE TABLE water_authority_station_owners (
          id               bigserial   PRIMARY KEY,
          source_owner_id  integer     NOT NULL,
          owner_code       text,
          name             text        NOT NULL,
          is_active        boolean     NOT NULL DEFAULT true,
          source_metadata  jsonb       NOT NULL DEFAULT '{}'::jsonb,
          synced_at        timestamptz NOT NULL,
          CONSTRAINT water_authority_station_owners_identity
            UNIQUE (source_owner_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX water_authority_station_owners_code_idx "
        "ON water_authority_station_owners (owner_code)"
    )

    # One row per key in get_hydro_stations_A7f3Q.php. The six discharge
    # thresholds correspond to 2, 5, 10, 20, 50 and 100-year return periods.
    # The provider's 999 sentinel means "not available" and must be persisted
    # as NULL by the loader, never as a real 999 m3/s threshold.
    op.execute(
        """
        CREATE TABLE hydrometric_stations (
          id                            bigserial PRIMARY KEY,
          source_station_id             integer     NOT NULL,
          name_he                       text,
          name_en                       text,
          location                      geography(Point, 4326) NOT NULL,
          owner_id                      bigint REFERENCES water_authority_station_owners(id),
          map_zoom_level                integer,
          flow_start_water_level_m      double precision,
          flow_threshold_2y_m3s         double precision,
          flow_threshold_5y_m3s         double precision,
          flow_threshold_10y_m3s        double precision,
          flow_threshold_20y_m3s        double precision,
          flow_threshold_50y_m3s        double precision,
          flow_threshold_100y_m3s       double precision,
          is_active                     boolean     NOT NULL DEFAULT true,
          source_metadata               jsonb       NOT NULL DEFAULT '{}'::jsonb,
          synced_at                     timestamptz NOT NULL,
          CONSTRAINT hydrometric_stations_identity
            UNIQUE (source_station_id),
          CONSTRAINT hydrometric_stations_has_name
            CHECK (name_he IS NOT NULL OR name_en IS NOT NULL),
          CONSTRAINT hydrometric_stations_threshold_2y_nonnegative
            CHECK (flow_threshold_2y_m3s IS NULL OR
                   (flow_threshold_2y_m3s >= 0 AND flow_threshold_2y_m3s <> 999)),
          CONSTRAINT hydrometric_stations_threshold_5y_nonnegative
            CHECK (flow_threshold_5y_m3s IS NULL OR
                   (flow_threshold_5y_m3s >= 0 AND flow_threshold_5y_m3s <> 999)),
          CONSTRAINT hydrometric_stations_threshold_10y_nonnegative
            CHECK (flow_threshold_10y_m3s IS NULL OR
                   (flow_threshold_10y_m3s >= 0 AND flow_threshold_10y_m3s <> 999)),
          CONSTRAINT hydrometric_stations_threshold_20y_nonnegative
            CHECK (flow_threshold_20y_m3s IS NULL OR
                   (flow_threshold_20y_m3s >= 0 AND flow_threshold_20y_m3s <> 999)),
          CONSTRAINT hydrometric_stations_threshold_50y_nonnegative
            CHECK (flow_threshold_50y_m3s IS NULL OR
                   (flow_threshold_50y_m3s >= 0 AND flow_threshold_50y_m3s <> 999)),
          CONSTRAINT hydrometric_stations_threshold_100y_nonnegative
            CHECK (flow_threshold_100y_m3s IS NULL OR
                   (flow_threshold_100y_m3s >= 0 AND flow_threshold_100y_m3s <> 999))
        )
        """
    )
    op.execute(
        "CREATE INDEX hydrometric_stations_location_idx "
        "ON hydrometric_stations USING GIST (location)"
    )
    op.execute(
        "CREATE INDEX hydrometric_stations_owner_id_idx "
        "ON hydrometric_stations (owner_id)"
    )

    # envista_id is an array of up to four rain-station source ids associated
    # with one hydrometric station. A link table preserves that many-to-many
    # relationship and the display order without four nullable columns.
    # rain_station_source_id intentionally has no FK yet: the rain-stations
    # table will be introduced with the rainfall ingestion work.
    op.execute(
        """
        CREATE TABLE hydrometric_station_rain_links (
          hydrometric_station_id  bigint   NOT NULL
            REFERENCES hydrometric_stations(id) ON DELETE CASCADE,
          rain_station_source_id  bigint   NOT NULL,
          link_order              smallint NOT NULL,
          synced_at               timestamptz NOT NULL,
          CONSTRAINT hydrometric_station_rain_links_pk
            PRIMARY KEY (hydrometric_station_id, rain_station_source_id),
          CONSTRAINT hydrometric_station_rain_links_order_identity
            UNIQUE (hydrometric_station_id, link_order),
          CONSTRAINT hydrometric_station_rain_links_order_range
            CHECK (link_order BETWEEN 1 AND 4)
        )
        """
    )
    op.execute(
        "CREATE INDEX hydrometric_station_rain_links_rain_station_idx "
        "ON hydrometric_station_rain_links (rain_station_source_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hydrometric_station_rain_links")
    op.execute("DROP TABLE IF EXISTS hydrometric_stations")
    op.execute("DROP TABLE IF EXISTS water_authority_station_owners")
