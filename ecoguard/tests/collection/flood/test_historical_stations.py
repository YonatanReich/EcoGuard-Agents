"""Historical Water Authority station registry parsing and matching."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ecoguard.collection.flood.historical_stations import (
    HistoricalStationRegistryError,
    UPSERT_HISTORICAL_STATION,
    automatic_station_links,
    fetch_historical_station_catalog,
    parse_historical_station_catalog,
)


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)


def _record(**overrides):
    record = {
        "_id": 1,
        "זיהוי תחנה": 1102,
        "שם עברית": "בצת-כביש 4",
        "שם אנגלית": "BEZET- ROAD 4",
        "תאריך הקמה": "27/01/2015",
        "שטח היקוות (קמ''ר)": 102,
        "שטח משותף": "לא",
        "נ.צ. X (רוחב)": 211086,
        "נ.צ. Y (רוחב)": 775565,
        "מספר קבוצה": None,
        "תחום התנקזות של נחל ראשי": "בצת",
        "סטטוס תחנה נוכחי": "לא פעילה",
    }
    record.update(overrides)
    return record


def test_parses_registry_fields_and_transforms_itm_coordinates():
    catalog = parse_historical_station_catalog([_record()], synced_at=NOW)

    row = catalog.rows[0]
    assert row["source_station_id"] == 1102
    assert row["established_on"].isoformat() == "2015-01-27"
    assert row["catchment_area_km2"] == 102.0
    assert row["shared_catchment"] is False
    assert 33.0 < row["longitude"] < 36.5
    assert 28.0 < row["latitude"] < 34.5
    assert row["is_in_current_registry"] is True


def test_rejects_duplicate_official_station_ids():
    with pytest.raises(HistoricalStationRegistryError, match="repeats identity 1102"):
        parse_historical_station_catalog([_record(), _record(_id=2)])


def test_rejects_unknown_boolean_values():
    with pytest.raises(HistoricalStationRegistryError, match="שטח משותף"):
        parse_historical_station_catalog([_record(**{"שטח משותף": "אולי"})])


def test_keeps_a_registry_station_without_coordinates_unmatched():
    catalog = parse_historical_station_catalog(
        [
            _record(
                **{
                    "נ.צ. X (רוחב)": None,
                    "נ.צ. Y (רוחב)": None,
                }
            )
        ]
    )

    assert catalog.rows[0]["latitude"] is None
    assert catalog.rows[0]["longitude"] is None
    assert automatic_station_links(catalog.rows, [], matched_at=NOW) == []


def test_upsert_types_nullable_coordinates_for_postgres():
    statement = str(UPSERT_HISTORICAL_STATION)

    assert "CAST(:longitude AS double precision)" in statement
    assert "CAST(:latitude AS double precision)" in statement


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class _HttpSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payload)


def test_fetches_registry_through_datastore_with_a_bounded_page():
    payload = {
        "success": True,
        "result": {"total": 1, "records": [_record()]},
    }
    http = _HttpSession(payload)

    catalog = fetch_historical_station_catalog(http)

    assert len(catalog.rows) == 1
    _, request = http.calls[0]
    assert request["params"]["resource_id"]
    assert request["params"]["limit"] == 1000
    assert request["params"]["offset"] == 0
    assert request["timeout"] == 60


def test_matches_same_location_even_when_live_name_is_shortened():
    historical = [
        {
            "source_station_id": 1102,
            "name_he": "בצת-כביש 4",
            "name_en": "BEZET- ROAD 4",
            "latitude": 33.0,
            "longitude": 35.0,
        }
    ]
    current = [
        {
            "id": 7,
            "name_he": "בצת",
            "name_en": "Betzet",
            "latitude": 33.0002,
            "longitude": 35.0002,
        }
    ]

    links = automatic_station_links(historical, current, matched_at=NOW)

    assert len(links) == 1
    assert links[0]["hydrometric_station_id"] == 7
    assert links[0]["match_method"] == "automatic_coordinates"
    assert links[0]["distance_m"] < 100
    assert links[0]["reviewed"] is False


def test_medium_distance_requires_name_support():
    historical = [
        {
            "source_station_id": 2105,
            "name_he": None,
            "name_en": "KEZIV HAZIV BRIDGE",
            "latitude": 33.0,
            "longitude": 35.0,
        }
    ]
    current = [
        {
            "id": 8,
            "name_he": None,
            "name_en": "KEZIV HAZIV BRIDGE",
            "latitude": 33.003,
            "longitude": 35.0,
        }
    ]

    links = automatic_station_links(historical, current, matched_at=NOW)

    assert len(links) == 1
    assert links[0]["match_method"] == "automatic_coordinates_name"
    assert 100 < links[0]["distance_m"] < 500


def test_does_not_force_a_distant_or_weak_name_match():
    historical = [
        {
            "source_station_id": 2105,
            "name_he": None,
            "name_en": "KEZIV HAZIV BRIDGE",
            "latitude": 33.0,
            "longitude": 35.0,
        }
    ]
    current = [
        {
            "id": 8,
            "name_he": None,
            "name_en": "UNRELATED STATION",
            "latitude": 33.003,
            "longitude": 35.0,
        },
        {
            "id": 9,
            "name_he": None,
            "name_en": "KEZIV HAZIV BRIDGE",
            "latitude": 33.02,
            "longitude": 35.0,
        },
    ]

    assert automatic_station_links(historical, current, matched_at=NOW) == []
