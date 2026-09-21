"""Make station eligibility explicit and remove obsolete flood history.

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
    # IMS publishes IDF curves separately from the live rain-station catalog.
    # Keep the curve grain relational so callers can select one duration and
    # return period without unpacking a station-sized JSON document. The
    # importer links every row to the existing rain station after validating
    # the complete 63-station source file.
    op.execute(
        """
        CREATE TABLE rain_station_idf_values (
          rain_station_id          bigint NOT NULL
            REFERENCES rain_stations(id) ON DELETE CASCADE,
          source_station_name_he   text NOT NULL,
          measure_type             text NOT NULL,
          number_of_years          smallint NOT NULL,
          duration_minutes         smallint NOT NULL,
          probability_percent      numeric(5, 2) NOT NULL,
          return_period_years      numeric(6, 1) NOT NULL,
          estimate                 double precision NOT NULL,
          lower_bound              double precision NOT NULL,
          upper_bound              double precision NOT NULL,
          match_method             text NOT NULL,
          source_dataset           text NOT NULL,
          imported_at              timestamptz NOT NULL,
          CONSTRAINT rain_station_idf_values_pk PRIMARY KEY (
            rain_station_id,
            measure_type,
            duration_minutes,
            probability_percent
          ),
          CONSTRAINT rain_station_idf_values_measure_type_valid
            CHECK (measure_type IN ('amount', 'intensity')),
          CONSTRAINT rain_station_idf_values_years_positive
            CHECK (number_of_years > 0),
          CONSTRAINT rain_station_idf_values_duration_positive
            CHECK (duration_minutes > 0),
          CONSTRAINT rain_station_idf_values_probability_range
            CHECK (probability_percent > 0 AND probability_percent <= 100),
          CONSTRAINT rain_station_idf_values_return_period_positive
            CHECK (return_period_years > 0),
          CONSTRAINT rain_station_idf_values_bounds_valid CHECK (
            lower_bound >= 0 AND
            estimate >= lower_bound AND
            upper_bound >= estimate
          ),
          CONSTRAINT rain_station_idf_values_match_method_valid CHECK (
            match_method IN ('official_name_exact', 'manual_override')
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX rain_station_idf_values_lookup_idx "
        "ON rain_station_idf_values "
        "(rain_station_id, duration_minutes, return_period_years)"
    )
    # The active detector uses only the official live-station threshold vector.
    # Drop the historical import pipeline and its derived baseline in dependency
    # order. The import metadata table is removed with the four domain tables
    # because it has no purpose without historical observations.
    op.execute("DROP TABLE IF EXISTS flood_station_baselines")
    op.execute("DROP TABLE IF EXISTS historical_hydrometric_observations")
    op.execute("DROP TABLE IF EXISTS historical_hydrograph_imports")
    op.execute("DROP TABLE IF EXISTS hydrometric_station_history_links")
    op.execute("DROP TABLE IF EXISTS historical_hydrometric_stations")
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
    op.execute("DROP TABLE IF EXISTS rain_station_idf_values")
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
    _restore_removed_history_schema()


def _restore_removed_history_schema() -> None:
    """Restore the pre-upgrade schema; removed source data cannot be recovered."""
    op.execute(
        """
        CREATE TABLE historical_hydrometric_stations (
          source_station_id        integer PRIMARY KEY,
          name_he                  text,
          name_en                  text,
          established_on          date,
          catchment_area_km2       double precision,
          shared_catchment         boolean,
          israel_grid_x            double precision,
          israel_grid_y            double precision,
          group_source_station_id  integer,
          main_drainage_name       text,
          current_status           text,
          location                 geography(Point, 4326),
          source_metadata          jsonb       NOT NULL DEFAULT '{}'::jsonb,
          synced_at                timestamptz NOT NULL,
          is_in_current_registry   boolean     NOT NULL DEFAULT true,
          CONSTRAINT historical_hydrometric_stations_has_name
            CHECK (name_he IS NOT NULL OR name_en IS NOT NULL),
          CONSTRAINT historical_hydrometric_stations_area_nonnegative
            CHECK (catchment_area_km2 IS NULL OR catchment_area_km2 >= 0),
          CONSTRAINT historical_hydrometric_stations_coordinates_complete
            CHECK (
              (israel_grid_x IS NULL AND israel_grid_y IS NULL AND location IS NULL) OR
              (israel_grid_x IS NOT NULL AND israel_grid_y IS NOT NULL AND location IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX historical_hydrometric_stations_location_idx "
        "ON historical_hydrometric_stations USING GIST (location)"
    )
    op.execute(
        "CREATE INDEX historical_hydrometric_stations_group_idx "
        "ON historical_hydrometric_stations (group_source_station_id)"
    )
    op.execute(
        """
        CREATE TABLE hydrometric_station_history_links (
          historical_station_id integer PRIMARY KEY
            REFERENCES historical_hydrometric_stations(source_station_id)
              ON DELETE CASCADE,
          hydrometric_station_id bigint NOT NULL
            REFERENCES hydrometric_stations(id) ON DELETE CASCADE,
          match_method           text NOT NULL,
          distance_m             double precision NOT NULL,
          name_similarity        real NOT NULL,
          confidence             real NOT NULL,
          reviewed               boolean NOT NULL DEFAULT false,
          matched_at             timestamptz NOT NULL,
          CONSTRAINT hydrometric_station_history_links_method CHECK (
            match_method IN (
              'automatic_coordinates',
              'automatic_coordinates_name',
              'manual'
            )
          ),
          CONSTRAINT hydrometric_station_history_links_distance_nonnegative
            CHECK (distance_m >= 0),
          CONSTRAINT hydrometric_station_history_links_similarity_range
            CHECK (name_similarity >= 0 AND name_similarity <= 1),
          CONSTRAINT hydrometric_station_history_links_confidence_range
            CHECK (confidence >= 0 AND confidence <= 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX hydrometric_station_history_links_current_idx "
        "ON hydrometric_station_history_links (hydrometric_station_id)"
    )
    op.execute(
        """
        CREATE TABLE historical_hydrograph_imports (
          id                  bigserial PRIMARY KEY,
          source_name         text        NOT NULL UNIQUE,
          content_sha256      text        NOT NULL UNIQUE,
          source_size_bytes   bigint      NOT NULL,
          row_count           integer     NOT NULL,
          station_count       integer     NOT NULL,
          first_observed_at   timestamptz NOT NULL,
          last_observed_at    timestamptz NOT NULL,
          imported_at         timestamptz NOT NULL,
          CONSTRAINT historical_hydrograph_imports_sha256 CHECK (
            content_sha256 ~ '^[0-9a-f]{64}$'
          ),
          CONSTRAINT historical_hydrograph_imports_counts_positive CHECK (
            source_size_bytes > 0 AND row_count > 0 AND station_count > 0
          ),
          CONSTRAINT historical_hydrograph_imports_time_order CHECK (
            last_observed_at >= first_observed_at
          )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE historical_hydrometric_observations (
          import_id             bigint NOT NULL
            REFERENCES historical_hydrograph_imports(id) ON DELETE CASCADE,
          source_row_number     integer NOT NULL,
          historical_station_id integer NOT NULL
            REFERENCES historical_hydrometric_stations(source_station_id)
              ON DELETE RESTRICT,
          station_name_he       text,
          station_name_en       text,
          hydrological_year     text        NOT NULL,
          observed_at           timestamptz NOT NULL,
          water_height_m        double precision,
          discharge_m3s         double precision,
          data_type             text        NOT NULL,
          flow_type             text        NOT NULL,
          record_type           text        NOT NULL,
          is_sewage             boolean     NOT NULL,
          CONSTRAINT historical_hydrometric_observations_pk
            PRIMARY KEY (import_id, source_row_number),
          CONSTRAINT historical_hydrometric_observations_row_positive
            CHECK (source_row_number >= 2),
          CONSTRAINT historical_hydrometric_observations_has_measurement CHECK (
            water_height_m IS NOT NULL OR discharge_m3s IS NOT NULL
          ),
          CONSTRAINT historical_hydrometric_observations_discharge_nonnegative
            CHECK (discharge_m3s IS NULL OR discharge_m3s >= 0),
          CONSTRAINT historical_hydrometric_observations_has_name CHECK (
            station_name_he IS NOT NULL OR station_name_en IS NOT NULL
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX historical_hydrometric_observations_station_time_idx "
        "ON historical_hydrometric_observations "
        "(historical_station_id, observed_at)"
    )
    op.execute(
        "CREATE INDEX historical_hydrometric_observations_time_idx "
        "ON historical_hydrometric_observations (observed_at)"
    )
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
