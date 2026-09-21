"""Water Authority static hydrology reference data

Revision ID: hydrology_static_layers
Revises: air_pollution_weather_merge
Create Date: 2026-09-10
"""

from alembic import op


revision = "hydrology_static_layers"
down_revision = "air_pollution_weather_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per upstream source records exactly which version is represented
    # in the reference tables. checked_at advances even when its checksum is
    # unchanged; loaded_at advances only when rows were actually synchronized.
    op.execute(
        """
        CREATE TABLE static_layer_imports (
          layer_name       text        PRIMARY KEY,
          source_url       text        NOT NULL,
          source_version   text        NOT NULL,
          content_sha256   text        NOT NULL,
          feature_count    integer     NOT NULL,
          checked_at       timestamptz NOT NULL,
          loaded_at        timestamptz NOT NULL
        )
        """
    )

    # The source mixes Polygon and MultiPolygon features. The loader normalises
    # both to MultiPolygon so every spatial query sees one stable PostGIS type.
    op.execute(
        """
        CREATE TABLE drainage_basins (
          id          bigserial PRIMARY KEY,
          basin_id    integer     NOT NULL,
          area_id     integer,
          name_he     text,
          name_en     text,
          area_code   integer,
          geometry    geometry(MultiPolygon, 4326) NOT NULL,
          properties  jsonb       NOT NULL DEFAULT '{}'::jsonb,
          imported_at timestamptz NOT NULL,
          CONSTRAINT drainage_basins_identity UNIQUE (basin_id)
        )
        """
    )
    op.execute("CREATE INDEX drainage_basins_geometry_idx ON drainage_basins USING GIST (geometry)")
    op.execute("CREATE INDEX drainage_basins_area_id_idx ON drainage_basins (area_id)")

    # LineString and MultiLineString features are likewise normalised to one
    # MultiLineString representation at ingestion time.
    op.execute(
        """
        CREATE TABLE streams (
          id                   bigserial PRIMARY KEY,
          object_id            integer     NOT NULL,
          name_he              text,
          water_source_id      bigint,
          main_catchment_code  text,
          main_catchment_name  text,
          draining_water_id    bigint,
          draining_water_name  text,
          geometry             geometry(MultiLineString, 4326) NOT NULL,
          properties           jsonb       NOT NULL DEFAULT '{}'::jsonb,
          imported_at          timestamptz NOT NULL,
          CONSTRAINT streams_identity UNIQUE (object_id)
        )
        """
    )
    op.execute("CREATE INDEX streams_geometry_idx ON streams USING GIST (geometry)")
    op.execute("CREATE INDEX streams_water_source_id_idx ON streams (water_source_id)")

    # Despite its filename, road_km.geojson is not a road network. It contains
    # one point for each labelled road kilometre, which is useful for reporting
    # a flood near "road 1, km 15" but cannot be used for route calculations.
    op.execute(
        """
        CREATE TABLE road_km_markers (
          id             bigserial PRIMARY KEY,
          object_id      integer          NOT NULL,
          road_number    text             NOT NULL,
          kilometer      double precision NOT NULL,
          israel_grid_x  double precision,
          israel_grid_y  double precision,
          road_type      text,
          location       geography(Point, 4326) NOT NULL,
          properties     jsonb            NOT NULL DEFAULT '{}'::jsonb,
          imported_at    timestamptz      NOT NULL,
          CONSTRAINT road_km_markers_identity UNIQUE (object_id)
        )
        """
    )
    op.execute("CREATE INDEX road_km_markers_location_idx ON road_km_markers USING GIST (location)")
    op.execute("CREATE INDEX road_km_markers_road_km_idx ON road_km_markers (road_number, kilometer)")

    # The station endpoint returns owners as a separate object keyed by its own
    # source id. Owners are shared reference data for hydrometric and future
    # rain stations, so they use a source-wide table rather than a station-type
    # specific table.
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
    # The provider's 999 sentinel is normalized to NULL by the loader.
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

    # envista_id contains up to four rain-station source ids associated with a
    # hydrometric station. The future rain-stations migration can add the
    # missing FK after that catalog has its own table.
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
    op.execute("DROP TABLE IF EXISTS road_km_markers")
    op.execute("DROP TABLE IF EXISTS streams")
    op.execute("DROP TABLE IF EXISTS drainage_basins")
    op.execute("DROP TABLE IF EXISTS static_layer_imports")
