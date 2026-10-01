"""Water Authority hydrometric station catalog parsing and retrieval."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ecoguard.collectors.flood.hydrometric_stations import (
    FLOW_REGIME_REFERENCE_PATH,
    HydrometricStationCatalogError,
    HydrometricStationFlowRegimeError,
    STATION_UPSERT,
    _validate_flow_regime_targets,
    fetch_hydrometric_station_catalog,
    parse_hydrometric_station_catalog,
    persist_hydrometric_station_flow_regimes,
    read_hydrometric_station_flow_regimes,
)


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _response():
    return [
        {
            "49": {
                "name_en": "HILLAZON-YASUR",
                "name_he": "חילזון-יסעור",
                "lat": 32.8948097229004,
                "lon": 35.1782989501953,
                "zoom": 2,
                "threshold": [17, 37, 48, 60, 72, 85],
                "envista_id": [205, None, 311, None],
                "owner_id": 2,
                "level_flow_start": -0.16,
            }
        },
        {"2": {"owner_code": "IHS", "name": "רשות המים"}},
        "hydrology text",
        "water-height text",
    ]


def test_parses_owners_stations_thresholds_and_rain_links():
    catalog = parse_hydrometric_station_catalog(_response(), synced_at=NOW)

    assert catalog.owners[0]["source_owner_id"] == 2
    station = catalog.stations[0]
    assert station["source_station_id"] == 49
    assert station["flow_start_water_level_m"] == -0.16
    assert station["flow_threshold_2y_m3s"] == 17
    assert station["flow_threshold_50y_m3s"] == 72
    assert station["flow_threshold_100y_m3s"] == 85
    assert station["flow_threshold_status"] == "complete_thresholds"
    assert "operational_flow_regime" not in station
    assert [(link["rain_station_source_id"], link["link_order"]) for link in catalog.rain_links] == [
        (205, 1),
        (311, 3),
    ]


def test_reviewed_flow_regime_reference_contains_69_unique_stations():
    records = read_hydrometric_station_flow_regimes()

    assert FLOW_REGIME_REFERENCE_PATH.is_file()
    assert len(records) == 69
    assert len({record["source_station_id"] for record in records}) == 69
    assert sum(
        record["operational_flow_regime"] == "ephemeral"
        for record in records
    ) == 48
    assert sum(
        record["operational_flow_regime"] == "flowing_baseline"
        for record in records
    ) == 21


def test_flow_regime_reference_rejects_duplicate_station(tmp_path):
    reference = tmp_path / "regimes.csv"
    reference.write_text(
        "source_station_id,station_name_he,operational_flow_regime\n"
        "49,חילזון,ephemeral\n"
        "49,חילזון,flowing_baseline\n",
        encoding="utf-8",
    )

    with pytest.raises(HydrometricStationFlowRegimeError, match="duplicate station 49"):
        read_hydrometric_station_flow_regimes(reference)


def test_catalog_upsert_leaves_flow_regime_owned_by_reference_loader():
    sql = " ".join(str(STATION_UPSERT).split())

    assert "operational_flow_regime" not in sql


def test_flow_regime_targets_must_be_active_with_complete_thresholds():
    records = [{
        "source_station_id": 49,
        "station_name_he": "חילזון-יסעור",
        "operational_flow_regime": "ephemeral",
    }]
    statuses = [{
        "source_station_id": 49,
        "is_active": False,
        "flow_threshold_status": "complete_thresholds",
    }]

    with pytest.raises(
        HydrometricStationFlowRegimeError,
        match="active stations with complete thresholds: 49",
    ):
        _validate_flow_regime_targets(records, statuses)


def test_flow_regime_validation_reports_unclassified_eligible_stations():
    records = [{
        "source_station_id": 49,
        "station_name_he": "חילזון-יסעור",
        "operational_flow_regime": "ephemeral",
    }]
    statuses = [
        {
            "source_station_id": 49,
            "is_active": True,
            "flow_threshold_status": "complete_thresholds",
        },
        {
            "source_station_id": 50,
            "is_active": True,
            "flow_threshold_status": "complete_thresholds",
        },
    ]

    assert _validate_flow_regime_targets(records, statuses) == [50]


def test_flow_regime_persistence_replaces_database_values(monkeypatch):
    calls = []

    class Result:
        def mappings(self):
            return iter([
                {
                    "source_station_id": 49,
                    "is_active": True,
                    "flow_threshold_status": "complete_thresholds",
                }
            ])

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, statement, parameters=None):
            calls.append((str(statement), parameters))
            if "SELECT source_station_id" in str(statement):
                return Result()
            return None

        def commit(self):
            calls.append(("commit", None))

    from ecoguard.database import engine

    monkeypatch.setattr(engine, "Session", FakeSession)
    records = [{
        "source_station_id": 49,
        "station_name_he": "חילזון-יסעור",
        "operational_flow_regime": "ephemeral",
    }]

    result = persist_hydrometric_station_flow_regimes(records)

    assert result == {"classified": 1, "unclassified_active_complete": 0}
    assert "SET operational_flow_regime = NULL" in calls[1][0]
    assert "SET operational_flow_regime = :operational_flow_regime" in calls[2][0]
    assert calls[2][1] == [{
        "source_station_id": 49,
        "operational_flow_regime": "ephemeral",
    }]
    assert calls[-1] == ("commit", None)


def test_marks_a_station_with_six_provider_sentinels_as_missing_thresholds():
    response = _response()
    response[0]["49"]["threshold"] = [999, 999, 999, 999, 999, 999]

    station = parse_hydrometric_station_catalog(response, synced_at=NOW).stations[0]

    assert station["flow_threshold_status"] == "missing_thresholds"
    assert all(
        station[f"flow_threshold_{period}y_m3s"] is None
        for period in (2, 5, 10, 20, 50, 100)
    )


def test_rejects_an_unknown_owner():
    response = _response()
    response[0]["49"]["owner_id"] = 999

    with pytest.raises(HydrometricStationCatalogError, match="unknown owner 999"):
        parse_hydrometric_station_catalog(response, synced_at=NOW)


def test_rejects_a_threshold_array_with_the_wrong_length():
    response = _response()
    response[0]["49"]["threshold"] = [17, 37]

    with pytest.raises(HydrometricStationCatalogError, match="six discharge thresholds"):
        parse_hydrometric_station_catalog(response, synced_at=NOW)


def test_rejects_duplicate_envista_ids_for_one_station():
    response = _response()
    response[0]["49"]["envista_id"] = [205, 205, None, None]

    with pytest.raises(HydrometricStationCatalogError, match="repeats rain station 205"):
        parse_hydrometric_station_catalog(response, synced_at=NOW)


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


def test_fetch_creates_a_page_session_then_posts_with_its_temporary_token():
    http = _HttpSession(_response())

    catalog = fetch_hydrometric_station_catalog(http)

    assert len(catalog.stations) == 1
    assert len(http.get_calls) == 1
    assert len(http.post_calls) == 1
    _, post = http.post_calls[0]
    assert post["data"] == {"lang": "he"}
    assert post["headers"]["X-SESSION-TOKEN"] == "temporary-token"
    assert post["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_fetch_rejects_a_page_without_a_session_token():
    http = _HttpSession(_response())
    http.get = lambda *args, **kwargs: _Response(text="<html></html>")

    with pytest.raises(HydrometricStationCatalogError, match="session token"):
        fetch_hydrometric_station_catalog(http)
