"""Offline checks for the bounded shared observation reader."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from ecoguard.database.repositories import observations


LOWER = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
UPPER = LOWER + timedelta(hours=1)


def compile_statement(**changes):
    values = {
        "source": "air_pollution",
        "ingested_after": LOWER,
        "after_id": 41,
        "ingested_through": UPPER,
        "limit": 250,
    }
    values.update(changes)
    return observations.observation_batch_statement(**values).compile(
        dialect=postgresql.dialect()
    )


def test_source_ingestion_boundary_and_stable_order_are_in_one_select():
    query = compile_statement()
    sql = " ".join(str(query).split())

    assert "observations.source =" in sql
    assert "observations.ingested_at >" in sql
    assert "observations.ingested_at =" in sql
    assert "observations.id >" in sql
    assert "observations.ingested_at <=" in sql
    assert "ORDER BY observations.ingested_at, observations.id" in sql
    assert query.params["source_1"] == "air_pollution"
    assert query.params["param_1"] == 250


@pytest.mark.parametrize("limit", [0, 5001, True])
def test_read_batch_size_is_bounded(limit):
    with pytest.raises(ValueError, match="limit must be between"):
        compile_statement(limit=limit)


def test_after_id_requires_an_ingestion_timestamp():
    with pytest.raises(ValueError, match="after_id requires"):
        compile_statement(ingested_after=None, after_id=41)


def test_reader_uses_one_session_and_one_select(monkeypatch):
    returned = [{"id": 42}, {"id": 43}]
    executed = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return returned

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            executed.append(statement)
            return Result()

    monkeypatch.setattr(observations, "Session", Session)
    result = observations.read_observations_batch(
        "air_pollution", ingested_after=LOWER, limit=2
    )

    assert result == returned
    assert len(executed) == 1


def test_air_pollution_history_query_is_exact_bounded_and_causal():
    query = observations.air_pollution_series_history_statement(
        station_id="42",
        channel_id="7001",
        pollutant="PM2.5",
        unit="µg/m³",
        prediction_time=UPPER,
    ).compile(dialect=postgresql.dialect())
    sql = " ".join(str(query).split())

    assert "observations.source =" in sql
    assert "observations.cell_id =" in sql
    assert "observations.issued_at IS NULL" in sql
    assert "observations.observed_at >=" in sql
    assert "observations.observed_at <=" in sql
    assert "ORDER BY observations.observed_at DESC, observations.id DESC" in sql
    assert query.params["source_1"] == "air_pollution"
    assert query.params["cell_id_1"] == "ministry:42:7001:PM2.5:%C2%B5g%2Fm%C2%B3"
    assert query.params["observed_at_2"] == UPPER
    assert query.params["param_1"] == 100


def test_air_pollution_history_reader_returns_chronological_rows(monkeypatch):
    newest_first = [
        {"id": 3, "observed_at": UPPER},
        {"id": 2, "observed_at": UPPER - timedelta(minutes=5)},
    ]

    class Result:
        def mappings(self):
            return self

        def all(self):
            return newest_first

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            return Result()

    monkeypatch.setattr(observations, "Session", Session)
    rows = observations.read_air_pollution_series_history(
        station_id="42",
        channel_id="7001",
        pollutant="NO2",
        unit="ppb",
        prediction_time=UPPER,
    )

    assert [row["id"] for row in rows] == [2, 3]


@pytest.mark.parametrize("year", [2024, 2025])
def test_air_pollution_history_never_returns_future_rows(year):
    prediction_time = datetime(2023, 12, 31, 23, 55, tzinfo=timezone.utc)
    query = observations.air_pollution_series_history_statement(
        station_id="42",
        channel_id="7001",
        pollutant="NO2",
        unit="ppb",
        prediction_time=prediction_time,
    ).compile(dialect=postgresql.dialect())

    assert query.params["observed_at_2"] == prediction_time
    assert year > query.params["observed_at_2"].year
