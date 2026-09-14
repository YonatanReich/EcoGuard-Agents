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
