"""compact versioned air pollution baselines

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-11
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add compact versioned air pollution baselines."""
    # Additive only: operational observations and all existing tables are untouched.
    op.execute("""
        CREATE TABLE air_pollution_station_catalog (
          provider text NOT NULL,
          station_id text NOT NULL,
          station_name text NOT NULL,
          availability jsonb NOT NULL,
          artifact_sha256 varchar(64) NOT NULL,
          imported_at timestamptz NOT NULL,
          CONSTRAINT air_pollution_station_catalog_pk PRIMARY KEY (provider, station_id),
          CONSTRAINT air_pollution_station_catalog_hash_ck CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$')
        )
    """)
    op.execute("""
        CREATE TABLE air_pollution_baseline_profiles (
          id bigserial PRIMARY KEY,
          provider text NOT NULL,
          station_id text NOT NULL,
          channel_id text NOT NULL,
          pollutant text NOT NULL,
          canonical_unit text NOT NULL,
          CONSTRAINT air_pollution_baseline_profiles_station_fk
            FOREIGN KEY (provider, station_id)
            REFERENCES air_pollution_station_catalog (provider, station_id) ON DELETE RESTRICT,
          CONSTRAINT air_pollution_baseline_profiles_identity
            UNIQUE (provider, station_id, channel_id, pollutant, canonical_unit)
        )
    """)
    op.execute("""
        CREATE TABLE air_pollution_baseline_versions (
          id bigserial PRIMARY KEY,
          profile_id bigint NOT NULL REFERENCES air_pollution_baseline_profiles(id) ON DELETE RESTRICT,
          parent_version_id bigint,
          content_sha256 varchar(64) NOT NULL,
          schema_version text NOT NULL,
          method_version text,
          source_name text NOT NULL,
          source_version text,
          training_start date NOT NULL,
          training_end date NOT NULL,
          imported_at timestamptz NOT NULL,
          generated_at timestamptz,
          aggregation_policy_version text NOT NULL,
          quality_policy_version text NOT NULL,
          coverage_status text NOT NULL,
          lifecycle_status text NOT NULL,
          source_metadata jsonb NOT NULL,
          aggregation_metadata jsonb NOT NULL,
          quality_metadata jsonb NOT NULL,
          coverage_metadata jsonb NOT NULL,
          CONSTRAINT air_pollution_baseline_versions_content UNIQUE (profile_id, content_sha256),
          CONSTRAINT air_pollution_baseline_versions_id_profile UNIQUE (id, profile_id),
          CONSTRAINT air_pollution_baseline_versions_parent_fk
            FOREIGN KEY (parent_version_id, profile_id)
            REFERENCES air_pollution_baseline_versions (id, profile_id) ON DELETE RESTRICT,
          CONSTRAINT air_pollution_baseline_versions_hash_ck CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
          CONSTRAINT air_pollution_baseline_versions_training_ck CHECK (training_end >= training_start),
          CONSTRAINT air_pollution_baseline_versions_coverage_ck
            CHECK (coverage_status IN ('FULL_BASELINE','PARTIAL_BASELINE','INSUFFICIENT_HISTORY')),
          CONSTRAINT air_pollution_baseline_versions_lifecycle_ck
            CHECK (lifecycle_status IN ('draft','active','superseded'))
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX air_pollution_baseline_versions_one_active
        ON air_pollution_baseline_versions (profile_id)
        WHERE lifecycle_status = 'active'
    """)
    op.execute("""
        CREATE TABLE air_pollution_baseline_buckets (
          id bigserial PRIMARY KEY,
          baseline_version_id bigint NOT NULL
            REFERENCES air_pollution_baseline_versions(id) ON DELETE RESTRICT,
          month integer NOT NULL,
          hour integer NOT NULL,
          status text NOT NULL,
          sample_count integer NOT NULL,
          distinct_days integer NOT NULL,
          distinct_years integer NOT NULL,
          years_present integer[] NOT NULL,
          mean double precision,
          median double precision,
          std double precision,
          mad double precision,
          p05 double precision,
          p25 double precision,
          p75 double precision,
          p95 double precision,
          CONSTRAINT air_pollution_baseline_buckets_identity UNIQUE (baseline_version_id, month, hour),
          CONSTRAINT air_pollution_baseline_buckets_month_ck CHECK (month BETWEEN 1 AND 12),
          CONSTRAINT air_pollution_baseline_buckets_hour_ck CHECK (hour BETWEEN 0 AND 23),
          CONSTRAINT air_pollution_baseline_buckets_status_ck CHECK (status IN ('ok','insufficient_history')),
          CONSTRAINT air_pollution_baseline_buckets_counts_ck CHECK (
            sample_count >= 0 AND distinct_days >= 0 AND distinct_years >= 0
            AND distinct_days <= sample_count AND distinct_years <= distinct_days
          ),
          CONSTRAINT air_pollution_baseline_buckets_years_ck
            CHECK (cardinality(years_present) = distinct_years),
          CONSTRAINT air_pollution_baseline_buckets_statistics_presence_ck CHECK (
            (sample_count = 0 AND mean IS NULL AND median IS NULL AND std IS NULL AND mad IS NULL
             AND p05 IS NULL AND p25 IS NULL AND p75 IS NULL AND p95 IS NULL)
            OR
            (sample_count > 0 AND mean IS NOT NULL AND median IS NOT NULL AND std IS NOT NULL
             AND mad IS NOT NULL AND p05 IS NOT NULL AND p25 IS NOT NULL AND p75 IS NOT NULL
             AND p95 IS NOT NULL)
          ),
          CONSTRAINT air_pollution_baseline_buckets_std_ck CHECK (std IS NULL OR std >= 0),
          CONSTRAINT air_pollution_baseline_buckets_mad_ck CHECK (mad IS NULL OR mad >= 0),
          CONSTRAINT air_pollution_baseline_buckets_quantiles_ck CHECK (
            p05 IS NULL OR (p05 <= p25 AND p25 <= median AND median <= p75 AND p75 <= p95)
          )
        )
    """)


def downgrade() -> None:
    """Remove compact versioned air pollution baselines."""
    # This migration is deliberately non-destructive in both directions.
    raise RuntimeError("0009 is additive-only; explicit data-retention review is required to remove it")
