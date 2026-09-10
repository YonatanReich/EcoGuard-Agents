"""Water Authority static hydrology reference layers

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-10
"""

from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per upstream file records exactly which version is in the three
    # reference tables. checked_at advances even when the checksum is unchanged;
    # loaded_at advances only when rows were actually replaced.
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS road_km_markers")
    op.execute("DROP TABLE IF EXISTS streams")
    op.execute("DROP TABLE IF EXISTS drainage_basins")
    op.execute("DROP TABLE IF EXISTS static_layer_imports")
