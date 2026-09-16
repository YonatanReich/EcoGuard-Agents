"""Runtime state and materialized context for the flood detector.

Revision ID: flood_detector_runtime
Revises: stream_network_graph
Create Date: 2026-09-16
"""

from alembic import op


revision = "flood_detector_runtime"
down_revision = "stream_network_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A station's grid cell changes only when either the catalog coordinates or
    # the national grid changes. Store it once instead of spatially joining on
    # every detector tick.
    op.execute("ALTER TABLE hydrometric_stations ADD COLUMN cell_id text")
    op.execute("CREATE INDEX hydrometric_stations_cell_id_idx ON hydrometric_stations (cell_id)")
    op.execute("ALTER TABLE rain_stations ADD COLUMN cell_id text")
    op.execute("CREATE INDEX rain_stations_cell_id_idx ON rain_stations (cell_id)")

    op.execute(
        """
        CREATE TABLE detector_cursors (
          detector_name       text        NOT NULL,
          source              text        NOT NULL,
          last_ingested_at    timestamptz NOT NULL,
          last_observation_id bigint      NOT NULL,
          updated_at          timestamptz NOT NULL,
          CONSTRAINT detector_cursors_pk PRIMARY KEY (detector_name, source),
          CONSTRAINT detector_cursors_observation_id_nonnegative
            CHECK (last_observation_id >= 0)
        )
        """
    )

    # This is the only spatial context read by the worker. The expensive joins
    # against DEM-derived cells, drainage polygons and streams are performed by
    # the explicit static-data refresh, not in the real-time path.
    op.execute(
        """
        CREATE TABLE flood_cell_context (
          cell_id                    text PRIMARY KEY,
          location                   geography(Point, 4326) NOT NULL,
          drainage_basin_id          bigint
            REFERENCES drainage_basins(id) ON DELETE SET NULL,
          drainage_basin_source_id   integer,
          elevation_m                real,
          slope_deg                  real,
          built_up_fraction          real,
          distance_to_stream_m       real,
          refreshed_at               timestamptz NOT NULL,
          CONSTRAINT flood_cell_context_built_up_range CHECK (
            built_up_fraction IS NULL OR
            (built_up_fraction >= 0 AND built_up_fraction <= 1)
          ),
          CONSTRAINT flood_cell_context_distance_nonnegative CHECK (
            distance_to_stream_m IS NULL OR distance_to_stream_m >= 0
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX flood_cell_context_location_idx "
        "ON flood_cell_context USING GIST (location)"
    )
    op.execute(
        "CREATE INDEX flood_cell_context_basin_idx "
        "ON flood_cell_context (drainage_basin_id)"
    )

    # Monthly buckets are a compact, operational seasonal baseline. They are
    # rebuilt from cached history by the static-data command and provide a
    # station-specific fallback when no official rating threshold is present.
    op.execute(
        """
        CREATE TABLE flood_station_baselines (
          hydrometric_station_id bigint NOT NULL
            REFERENCES hydrometric_stations(id) ON DELETE CASCADE,
          month                  smallint NOT NULL,
          discharge_sample_count integer NOT NULL,
          discharge_distinct_days integer NOT NULL,
          stage_sample_count     integer NOT NULL,
          stage_distinct_days    integer NOT NULL,
          covered_months         smallint NOT NULL,
          history_span_days      integer NOT NULL,
          discharge_median_m3s   double precision,
          discharge_p95_m3s      double precision,
          stage_median_m         double precision,
          stage_p95_m            double precision,
          computed_at            timestamptz NOT NULL,
          CONSTRAINT flood_station_baselines_pk
            PRIMARY KEY (hydrometric_station_id, month),
          CONSTRAINT flood_station_baselines_month_range
            CHECK (month BETWEEN 1 AND 12),
          CONSTRAINT flood_station_baselines_coverage_range
            CHECK (covered_months BETWEEN 1 AND 12 AND history_span_days >= 0),
          CONSTRAINT flood_station_baselines_counts_nonnegative CHECK (
            discharge_sample_count >= 0 AND
            discharge_distinct_days >= 0 AND
            stage_sample_count >= 0 AND
            stage_distinct_days >= 0
          )
        )
        """
    )

    # One mapping row says which radar pixels cover a 5 km operational cell.
    # It is keyed by radar geometry because the map can be reused for every
    # frame with the same projection and dimensions.
    op.execute(
        """
        CREATE TABLE radar_cell_mappings (
          geometry_signature text NOT NULL,
          cell_id             text NOT NULL,
          latitude            double precision NOT NULL,
          longitude           double precision NOT NULL,
          row_start           integer NOT NULL,
          row_end             integer NOT NULL,
          column_start        integer NOT NULL,
          column_end          integer NOT NULL,
          created_at          timestamptz NOT NULL,
          CONSTRAINT radar_cell_mappings_pk
            PRIMARY KEY (geometry_signature, cell_id),
          CONSTRAINT radar_cell_mappings_valid_window CHECK (
            row_start >= 0 AND column_start >= 0 AND
            row_end > row_start AND column_end > column_start
          )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE flood_candidates (
          id                     bigserial PRIMARY KEY,
          event_key              text NOT NULL,
          candidate_key          text NOT NULL,
          cell_id                text NOT NULL,
          observed_at            timestamptz NOT NULL,
          location               geography(Point, 4326) NOT NULL,
          confidence             double precision NOT NULL,
          severity_hint          text NOT NULL,
          location_uncertainty_m double precision NOT NULL,
          trigger                text NOT NULL,
          evidence               jsonb NOT NULL DEFAULT '{}'::jsonb,
          emitted_at             timestamptz NOT NULL,
          status                 text NOT NULL DEFAULT 'active',
          resolved_at            timestamptz,
          resolution_reason      text,
          resolution_evidence    jsonb,
          CONSTRAINT flood_candidates_identity UNIQUE (candidate_key),
          CONSTRAINT flood_candidates_confidence_range
            CHECK (confidence >= 0 AND confidence <= 1),
          CONSTRAINT flood_candidates_severity
            CHECK (severity_hint IN ('low', 'moderate', 'high', 'critical')),
          CONSTRAINT flood_candidates_uncertainty_nonnegative
            CHECK (location_uncertainty_m >= 0),
          CONSTRAINT flood_candidates_status
            CHECK (status IN ('active', 'resolved')),
          CONSTRAINT flood_candidates_resolution_consistent CHECK (
            (status = 'active' AND resolved_at IS NULL) OR
            (status = 'resolved' AND resolved_at IS NOT NULL)
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX flood_candidates_observed_at_idx "
        "ON flood_candidates (observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX flood_candidates_location_idx "
        "ON flood_candidates USING GIST (location)"
    )
    op.execute(
        "CREATE UNIQUE INDEX flood_candidates_one_active_event_idx "
        "ON flood_candidates (event_key) WHERE status = 'active'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS flood_candidates")
    op.execute("DROP TABLE IF EXISTS radar_cell_mappings")
    op.execute("DROP TABLE IF EXISTS flood_station_baselines")
    op.execute("DROP TABLE IF EXISTS flood_cell_context")
    op.execute("DROP TABLE IF EXISTS detector_cursors")
    op.execute("DROP INDEX IF EXISTS rain_stations_cell_id_idx")
    op.execute("ALTER TABLE rain_stations DROP COLUMN IF EXISTS cell_id")
    op.execute("DROP INDEX IF EXISTS hydrometric_stations_cell_id_idx")
    op.execute("ALTER TABLE hydrometric_stations DROP COLUMN IF EXISTS cell_id")
