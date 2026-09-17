import pytest
from sqlalchemy import BigInteger
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import Values

from ecoguard.database.repositories.air_pollution_baseline_lookup import (
    batch_exact_baseline_statement, exact_baseline_statement,
)


IDENTITY = {
    "provider": "provider",
    "station_id": "station",
    "channel_id": "channel",
    "pollutant": "NO2",
    "canonical_unit": "µg/m³",
    "baseline_family": "completed_hour",
    "month": 7,
    "hour": 14,
}


def compiled(statement):
    return statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True},
    )


def values_column(statement, name):
    relation = next(
        element for element in visitors.iterate(statement)
        if isinstance(element, Values)
    )
    return relation.c[name]


def test_exact_statement_constrains_every_identity_dimension_and_bucket():
    query = compiled(exact_baseline_statement(**IDENTITY))
    sql = str(query)

    assert sql.lstrip().startswith("SELECT ")
    assert "air_pollution_baseline_profiles.channel_id =" in sql
    assert "air_pollution_baseline_profiles.pollutant =" in sql
    assert "air_pollution_baseline_profiles.canonical_unit =" in sql
    assert "air_pollution_baseline_profiles.baseline_family =" in sql
    assert "air_pollution_station_catalog.provider =" in sql
    assert "air_pollution_station_catalog.station_id =" in sql
    assert "air_pollution_baseline_buckets.month =" in sql
    assert "air_pollution_baseline_buckets.hour =" in sql
    assert "air_pollution_baseline_versions.lifecycle_status =" in sql
    assert set(IDENTITY.values()) <= set(query.params.values())
    assert "active" in query.params.values()


def test_draft_validation_can_pin_one_version_explicitly():
    query = compiled(exact_baseline_statement(
        **IDENTITY, lifecycle_status="draft", baseline_version_id=42,
    ))
    sql = str(query)

    assert "air_pollution_baseline_versions.id =" in sql
    assert "draft" in query.params.values()
    assert 42 in query.params.values()


@pytest.mark.parametrize("lifecycle", ["superseded", "", "ACTIVE"])
def test_non_operational_lifecycle_modes_are_rejected(lifecycle):
    with pytest.raises(ValueError):
        exact_baseline_statement(**IDENTITY, lifecycle_status=lifecycle)


def test_batch_statement_is_one_values_driven_exact_select():
    request = {"request_index": 0, **IDENTITY, "baseline_version_id": None}
    query = compiled(batch_exact_baseline_statement(
        [request, {**request, "request_index": 1}], lifecycle_status="draft",
    ))
    sql = str(query)

    assert sql.lstrip().startswith("SELECT ")
    assert "VALUES" in sql
    assert "requested_air_pollution_baselines" in sql
    assert "air_pollution_baseline_profiles.baseline_family = requested_air_pollution_baselines.baseline_family" in sql
    assert "air_pollution_baseline_buckets.month = requested_air_pollution_baselines.month" in sql
    assert "air_pollution_baseline_buckets.hour = requested_air_pollution_baselines.hour" in sql
    assert "air_pollution_baseline_versions.lifecycle_status =" in sql
    assert "draft" in query.params.values()


def test_all_null_batch_version_ids_are_explicitly_bigint():
    request = {"request_index": 0, **IDENTITY, "baseline_version_id": None}
    statement = batch_exact_baseline_statement(
        [request, {**request, "request_index": 1}], lifecycle_status="draft",
    )

    assert isinstance(values_column(statement, "baseline_version_id").type, BigInteger)
    query = compiled(statement)
    sql = str(query)
    values_sql = sql.split(") AS requested_air_pollution_baselines", 1)[0].rsplit(
        "VALUES ", 1,
    )[1]
    assert values_sql.count("NULL") == 2
    assert all(value is not None for value in query.params.values())


def test_explicit_numeric_batch_version_id_remains_bigint_and_joined():
    request = {"request_index": 0, **IDENTITY, "baseline_version_id": 42}
    statement = batch_exact_baseline_statement([request], lifecycle_status="draft")
    query = compiled(statement)

    assert isinstance(values_column(statement, "baseline_version_id").type, BigInteger)
    assert 42 in query.params.values()
    sql = str(query)
    assert "air_pollution_baseline_versions.id = CAST(" in sql
    assert "requested_air_pollution_baselines.baseline_version_id AS BIGINT" in sql


def test_batch_reader_uses_one_session_and_one_execute_for_current_scale(monkeypatch):
    from ecoguard.database.repositories import air_pollution_baseline_lookup as repository

    class EmptyResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeSession:
        def __init__(self):
            self.executions = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            self.executions += 1
            return EmptyResult()

    session = FakeSession()
    creations = []

    def session_factory():
        creations.append(session)
        return session

    monkeypatch.setattr(repository, "Session", session_factory)
    request = {"request_index": 0, **IDENTITY, "baseline_version_id": None}
    requests = [{**request, "request_index": index} for index in range(541)]

    assert repository.read_exact_baseline_candidates_batch(
        requests=requests, lifecycle_status="draft",
    ) == []
    assert creations == [session]
    assert session.executions == 1
