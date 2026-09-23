"""Parsing and retrieval of Water Authority hydrometric observations."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ecoguard.collectors.flood.hydrometric_observations import (
    HydrometricObservationError,
    fetch_hydrometric_observations,
    parse_hydrometric_observations,
)


def _payload():
    return [
        {
            "2026-09-10 12:20:00": {
                "50": [0, -0.04],
                "51": [None, -0.05],
            },
            "2026-09-10 12:30:00": {"50": [0.29, 0.23]},
        },
        {"2026-09-10 12:20:00": "IMSRadar4GIS_202609101220_0.png"},
        "2026-09-10 12:30:00",
    ]


def test_parses_flow_height_and_israel_local_time():
    batch = parse_hydrometric_observations(_payload())

    assert len(batch.rows) == 3
    first = batch.rows[0]
    assert first["source_station_id"] == 50
    assert first["discharge_m3s"] == 0
    assert first["water_height_m"] == -0.04
    assert first["observed_at"] == datetime(
        2026, 9, 10, 9, 20, tzinfo=timezone.utc
    )
    assert batch.provider_latest_at == datetime(
        2026, 9, 10, 9, 30, tzinfo=timezone.utc
    )
    assert batch.radar_frame_count == 1


def test_accepts_a_missing_discharge_without_fabricating_it():
    batch = parse_hydrometric_observations(_payload())

    row = next(row for row in batch.rows if row["source_station_id"] == 51)
    assert row["discharge_m3s"] is None
    assert row["water_height_m"] == -0.05


def test_rejects_a_row_without_any_measurement():
    payload = _payload()
    payload[0]["2026-09-10 12:20:00"]["50"] = [None, None]

    with pytest.raises(HydrometricObservationError, match="has no measurement"):
        parse_hydrometric_observations(payload)


def test_rejects_an_unexpected_value_shape():
    payload = _payload()
    payload[0]["2026-09-10 12:20:00"]["50"] = [0.4]

    with pytest.raises(HydrometricObservationError, match="water height"):
        parse_hydrometric_observations(payload)


def test_rejects_a_latest_time_older_than_an_observation():
    payload = _payload()
    payload[2] = "2026-09-10 12:00:00"

    with pytest.raises(HydrometricObservationError, match="precedes"):
        parse_hydrometric_observations(payload)


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


def test_fetch_uses_a_page_session_and_does_not_request_radar_files():
    http = _HttpSession(_payload())

    batch = fetch_hydrometric_observations(http)

    assert len(batch.rows) == 3
    assert len(http.get_calls) == 1
    assert len(http.post_calls) == 1
    url, post = http.post_calls[0]
    assert url.endswith("/db_requests/get_hydro_observations_A7f3Q.php")
    assert post["headers"]["X-SESSION-TOKEN"] == "temporary-token"
    assert "data" not in post


def test_fetch_rejects_a_page_without_a_session_token():
    http = _HttpSession(_payload())
    http.get = lambda *args, **kwargs: _Response(text="<html></html>")

    with pytest.raises(HydrometricObservationError, match="session token"):
        fetch_hydrometric_observations(http)
