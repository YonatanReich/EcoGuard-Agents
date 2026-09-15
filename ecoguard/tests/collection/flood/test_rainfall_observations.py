"""Parsing and retrieval of Water Authority numeric rainfall observations."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from ecoguard.collection.flood.rainfall_observations import (
    RainfallObservationError,
    _database_rows,
    _rainfall_observation_upsert,
    fetch_rainfall_observations,
    parse_rainfall_observations,
)


def _payload():
    return [
        {
            "205": {
                "2026-09-10 12:20:00": 0.4,
                "2026-09-10 12:30:00": 1,
            },
            # Unknown source ids are retained even when station metadata has
            # not yet caught up with the observation window.
            "999": {"2026-09-10 12:30:00": 0.2},
        },
        {
            "205": {
                "name": "Example Rain Station",
                "name_he": "תחנת גשם לדוגמה",
                "lat": 32.8174,
                "lon": 35.7622,
                "owner_id": 1,
            }
        },
        {
            "205": {
                "24": 5.7,
                "12": 3.1,
                "6": 1.4,
                "24h": {
                    "2026-09-10 11:00:00": 0.8,
                    "2026-09-10 12:00:00": 1.4,
                },
                "year": 114.3,
                "month": 12.6,
            }
        },
        "2026-09-10 12:30:00",
        "2026-09-10 12:37:00",
    ]


def test_parses_stations_ten_minute_rain_and_accumulations():
    batch = parse_rainfall_observations(_payload())

    assert batch.provider_latest_at == datetime(
        2026, 9, 10, 9, 30, tzinfo=timezone.utc
    )
    assert batch.provider_response_at == datetime(
        2026, 9, 10, 9, 37, tzinfo=timezone.utc
    )
    assert batch.stations[0] == {
        "source_station_id": 205,
        "name_he": "תחנת גשם לדוגמה",
        "name_en": "Example Rain Station",
        "latitude": 32.8174,
        "longitude": 35.7622,
        "source_owner_id": 1,
        "source_metadata": _payload()[1]["205"],
    }

    assert len(batch.rows) == 3
    first = batch.rows[0]
    assert first["source_station_id"] == 205
    assert first["observed_at"] == datetime(
        2026, 9, 10, 9, 20, tzinfo=timezone.utc
    )
    assert first["rainfall_mm"] == 0.4
    assert first["source_payload"] == 0.4

    summary = batch.accumulations[0]
    assert summary["rainfall_6h_mm"] == 1.4
    assert summary["rainfall_12h_mm"] == 3.1
    assert summary["rainfall_24h_mm"] == 5.7
    assert summary["rainfall_month_mm"] == 12.6
    assert summary["rainfall_season_mm"] == 114.3
    assert summary["hourly_values"]["2026-09-10 12:00:00"] == 1.4


def test_rejects_negative_rainfall():
    payload = _payload()
    payload[0]["205"]["2026-09-10 12:20:00"] = -0.1

    with pytest.raises(RainfallObservationError, match="cannot be negative"):
        parse_rainfall_observations(payload)


def test_rejects_station_ids_that_only_differ_by_zero_padding():
    payload = _payload()
    payload[1]["0205"] = dict(payload[1]["205"])

    with pytest.raises(RainfallObservationError, match="duplicate rain station id 205"):
        parse_rainfall_observations(payload)


def test_preserves_an_unavailable_accumulation_as_null():
    payload = _payload()
    del payload[2]["205"]["6"]
    del payload[2]["205"]["24h"]

    summary = parse_rainfall_observations(payload).accumulations[0]

    assert summary["rainfall_6h_mm"] is None
    assert summary["hourly_values"] is None


def test_rejects_a_non_object_hourly_accumulation():
    payload = _payload()
    payload[2]["205"]["24h"] = 4.2

    with pytest.raises(RainfallObservationError, match="hourly values must be an object"):
        parse_rainfall_observations(payload)


def test_rejects_a_latest_time_older_than_an_observation():
    payload = _payload()
    payload[3] = "2026-09-10 12:00:00"

    with pytest.raises(RainfallObservationError, match="precedes"):
        parse_rainfall_observations(payload)


def test_database_rows_keep_unknown_source_stations_unlinked():
    batch = parse_rainfall_observations(_payload())
    collected_at = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)

    observations, accumulations, unlinked = _database_rows(
        batch, {205: 700}, collected_at
    )

    assert observations[0]["rain_station_id"] == 700
    assert next(
        row for row in observations if row["source_station_id"] == 999
    )["rain_station_id"] is None
    assert accumulations[0]["rain_station_id"] == 700
    assert unlinked == 1
    assert all(row["collected_at"] == collected_at for row in observations)
    assert all(row["collected_at"] == collected_at for row in accumulations)


def test_observation_upsert_only_updates_a_changed_rainfall_value():
    statement = _rainfall_observation_upsert(
        [
            {
                "source_station_id": 205,
                "rain_station_id": 700,
                "observed_at": datetime(2026, 9, 10, 9, 20, tzinfo=timezone.utc),
                "rainfall_mm": 0.6,
                "source_payload": 0.6,
                "collected_at": datetime(2026, 9, 10, 9, 30, tzinfo=timezone.utc),
            }
        ]
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert (
        "ON CONFLICT ON CONSTRAINT rainfall_observations_identity DO UPDATE" in sql
    )
    assert "rainfall_mm = excluded.rainfall_mm" in sql
    assert (
        "WHERE rainfall_observations.rainfall_mm "
        "IS DISTINCT FROM excluded.rainfall_mm" in sql
    )


class _Response:
    def __init__(self, *, text="", payload=None):
        self.text = text
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _HttpSession:
    def __init__(self, payload):
        self.payload = payload
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return _Response(text='<meta name="api-token" content="temporary-token">')

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return _Response(payload=self.payload)


def test_fetch_uses_the_numeric_rain_endpoint_and_page_session():
    http = _HttpSession(_payload())

    batch = fetch_rainfall_observations(http)

    assert len(batch.rows) == 3
    assert len(http.get_calls) == 1
    assert len(http.post_calls) == 1
    url, post = http.post_calls[0]
    assert url.endswith("/db_requests/get_rain_observations_A7f3Q.php")
    assert post["headers"]["X-SESSION-TOKEN"] == "temporary-token"
    assert "data" not in post


def test_fetch_rejects_a_page_without_a_session_token():
    http = _HttpSession(_payload())
    http.get = lambda *args, **kwargs: _Response(text="<html></html>")

    with pytest.raises(RainfallObservationError, match="session token"):
        fetch_rainfall_observations(http)
