"""PostgreSQL DDL contract checks; no engine or database connection."""

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from ecoguard.database.models import (
    AirPollutionBaselineBucket, AirPollutionBaselineProfile,
    AirPollutionBaselineVersion, AirPollutionStationCatalog, Base,
)


def ddl(model):
    return str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))


def test_models_are_registered_and_additive():
    names = set(Base.metadata.tables)
    assert {"observations", "collector_runs"} <= names
    assert {"air_pollution_station_catalog", "air_pollution_baseline_profiles",
            "air_pollution_baseline_versions", "air_pollution_baseline_buckets"} <= names


def test_stable_profile_and_bucket_identities():
    profile_uniques = {tuple(c.columns.keys()) for c in AirPollutionBaselineProfile.__table__.constraints
                       if isinstance(c, UniqueConstraint)}
    bucket_uniques = {tuple(c.columns.keys()) for c in AirPollutionBaselineBucket.__table__.constraints
                      if isinstance(c, UniqueConstraint)}
    assert ("provider", "station_id", "channel_id", "pollutant", "canonical_unit",
            "baseline_family") in profile_uniques
    assert ("baseline_version_id", "month", "hour") in bucket_uniques


def test_one_active_partial_index():
    index, = [i for i in AirPollutionBaselineVersion.__table__.indexes if i.name.endswith("one_active")]
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE INDEX" in sql and "WHERE lifecycle_status = 'active'" in sql


def test_family_is_required_and_constrained():
    column = AirPollutionBaselineProfile.__table__.c.baseline_family
    assert column.nullable is False and column.default is None
    checks = " ".join(str(c.sqltext) for c in AirPollutionBaselineProfile.__table__.constraints
                      if isinstance(c, CheckConstraint))
    assert "completed_hour" in checks and "five_minute_observation" in checks


def test_same_measurement_identity_can_have_both_families():
    common = dict(provider="provider", station_id="1", channel_id="4",
                  pollutant="NO2", canonical_unit="µg/m³")
    completed = AirPollutionBaselineProfile(
        **common, baseline_family="completed_hour",
    )
    immediate = AirPollutionBaselineProfile(
        **common, baseline_family="five_minute_observation",
    )
    assert completed.baseline_family != immediate.baseline_family
    assert all(getattr(completed, field) == getattr(immediate, field)
               for field in common)


def test_active_uniqueness_is_per_family_specific_profile():
    index, = [i for i in AirPollutionBaselineVersion.__table__.indexes
              if i.name.endswith("one_active")]
    assert tuple(index.columns.keys()) == ("profile_id",)
    # Family is intentionally not duplicated onto versions: separate profile
    # IDs make the unchanged partial index independent per family.
    assert "baseline_family" not in AirPollutionBaselineVersion.__table__.c


def test_bucket_ddl_allows_signed_statistics_but_constrains_spread_and_time():
    sql = ddl(AirPollutionBaselineBucket)
    assert "month BETWEEN 1 AND 12" in sql and "hour BETWEEN 0 AND 23" in sql
    assert "std IS NULL OR std >= 0" in sql and "mad IS NULL OR mad >= 0" in sql
    assert "mean >= 0" not in sql and "median >= 0" not in sql and "p05 >= 0" not in sql
    assert "cardinality(years_present) = distinct_years" in sql


def test_version_metadata_and_separate_states():
    columns = set(AirPollutionBaselineVersion.__table__.columns.keys())
    assert {"content_sha256", "parent_version_id", "schema_version", "method_version",
            "source_version", "training_start", "training_end", "imported_at", "generated_at",
            "aggregation_policy_version", "quality_policy_version", "coverage_status",
            "lifecycle_status"} <= columns
    checks = " ".join(str(c.sqltext) for c in AirPollutionBaselineVersion.__table__.constraints
                      if isinstance(c, CheckConstraint))
    assert "FULL_BASELINE" in checks and "PARTIAL_BASELINE" in checks
    assert "draft" in checks and "active" in checks and "superseded" in checks
    parent = next(c for c in AirPollutionBaselineVersion.__table__.foreign_key_constraints
                  if c.name == "air_pollution_baseline_versions_parent_fk")
    assert tuple(parent.column_keys) == ("parent_version_id", "profile_id")
