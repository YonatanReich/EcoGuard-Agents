"""Flood-only normalized observation writes."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from ecoguard.database.repositories.flood_observations import (
    upsert_flood_observations_in_session,
)


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)


class Result:
    def scalars(self):
        return self

    def all(self):
        return [1]


class Session:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return Result()


def test_corrected_flood_payload_updates_the_normalized_stream():
    session = Session()
    records = [
        {
            "cell_id": "risk-05000m-r0040-c0012",
            "latitude": 32.0,
            "longitude": 34.8,
            "observed_at": NOW,
            "payload": {"rainfall_mm": 4.0},
        }
    ]

    written = upsert_flood_observations_in_session(
        session,
        "water_authority_rainfall_observations",
        records,
        ingested_at=NOW,
    )

    sql = str(
        session.statements[0].compile(dialect=postgresql.dialect())
    )
    assert written == 1
    assert "ON CONFLICT ON CONSTRAINT observations_identity DO UPDATE" in sql
    assert "payload IS DISTINCT FROM excluded.payload" in sql


def test_flood_observation_timestamps_must_be_timezone_aware():
    with pytest.raises(ValueError, match="ingested_at must carry a UTC offset"):
        upsert_flood_observations_in_session(
            Session(),
            "water_authority_rainfall_observations",
            [],
            ingested_at=datetime(2026, 9, 16, 8, 0),
        )
