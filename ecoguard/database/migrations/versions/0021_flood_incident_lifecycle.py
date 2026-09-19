"""Move flood lifecycle ownership to shared incidents.

Revision ID: flood_incident_lifecycle
Revises: hydrometric_idf_basin_links, resource_allocations,
         event_projections_towns_merge
Create Date: 2026-09-18
"""

from alembic import op


revision = "flood_incident_lifecycle"
down_revision = (
    "hydrometric_idf_basin_links",
    "resource_allocations",
    "event_projections_towns_merge",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve every old flood lifecycle row before removing the parallel
    # store. Active rows continue as open shared incidents and resolved rows
    # remain queryable history.
    op.execute(
        """
        INSERT INTO incidents (
          id, status, primary_hazard, hazards, queues, cells,
          latitude, longitude, precision_m, location_method,
          first_seen_at, last_signal_at, closed_at,
          signal_count, peak_rarity, links, signals
        )
        SELECT
          'INC-FLOOD-LEGACY-' || candidate.id::text,
          CASE candidate.status WHEN 'active' THEN 'open' ELSE 'closed' END,
          'flood', ARRAY['flood']::text[], ARRAY['emergency']::text[],
          ARRAY[candidate.cell_id]::text[],
          ST_Y(candidate.location::geometry),
          ST_X(candidate.location::geometry),
          candidate.location_uncertainty_m::real,
          'hydrometric_station',
          candidate.observed_at,
          candidate.observed_at,
          candidate.resolved_at,
          1,
          NULL,
          '[]'::jsonb,
          jsonb_build_array(
            jsonb_build_object(
              'cell_id', candidate.cell_id,
              'observed_at', candidate.observed_at,
              'hazard', 'flood',
              'variable', 'discharge',
              'value', candidate.evidence->'current_discharge',
              'unit', 'm3/s',
              'source', 'water_authority_hydrometric_observations',
              'rarity', NULL,
              'direction', 'high',
              'baseline', NULL,
              'location', jsonb_build_object(
                'latitude', ST_Y(candidate.location::geometry),
                'longitude', ST_X(candidate.location::geometry),
                'precision_m', candidate.location_uncertainty_m,
                'method', 'hydrometric_station'
              ),
              'confidence', candidate.confidence,
              'severity', NULL,
              'evidence', candidate.evidence
            )
          )
        FROM flood_candidates AS candidate
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.execute("DROP TABLE flood_candidates")
    op.execute("DROP TABLE detector_cursors")
    op.execute("DROP TABLE hydrometric_observations")


def downgrade() -> None:
    # The old tables are recreated for code rollback. Shared incidents are not
    # deleted: a downgrade must not destroy events recorded after the upgrade.
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
