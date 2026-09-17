"""Offline operational compatibility, without DB imports or provider requests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest

from ecoguard.shared.air_quality_schemas import LIVE_QUALITY_POLICY
from ecoguard.detectors.air_pollution.hourly import (
    AGGREGATION_POLICY, aggregate_hour, provider_clock,
    provider_hour_for_observation,
)
from ecoguard.shared.ministry_air_quality_client import MinistryAirQualityClient
from ecoguard.tests.collection.pollution.test_ministry_air_quality_client import FakeSession, routes_for, channel, station

HOUR = datetime(2026, 7, 1, 8, tzinfo=timezone.utc)


def collect(value=1., unit="ug/m3", metadata=None, **changes):
    reading = {**channel("PM10", value, unit=unit), **changes}
    stations = [station(monitors=[{"channelId": 101, "name": "PM10", "units": metadata, "active": True}])] if metadata else None
    return MinistryAirQualityClient(session=FakeSession(routes_for({17: [reading]}, stations=stations))).collect_latest()


@pytest.mark.parametrize("unit,metadata,source,effective,actual", [
    ("ug/m3", "ppb", "reading", "µg/m³", "µg/m³"),
    (None, "ppb", "metadata_fallback", "ppb", None),
    ("", "ppb", "metadata_fallback", "ppb", None),
    (None, None, "unknown", None, None),
])
def test_unit_provenance(unit, metadata, source, effective, actual):
    obs, = collect(unit=unit, metadata=metadata).observations
    assert (obs.unit_source, obs.unit, obs.measurement_unit) == (source, effective, actual)
    assert obs.metadata_unit == metadata
    assert obs.reading_unit == (unit or None)


def test_signed_and_provider_status_evidence():
    obs, = collect(-3.5, status=5, state="Calib").observations
    assert obs.value == -3.5 and obs.valid is True
    assert obs.provider_status_id == "5" and obs.provider_status == "Calib"
    assert obs.quality_policy == LIVE_QUALITY_POLICY


@pytest.mark.parametrize("value", [None, True, "bad", -9999, float("inf"), float("-inf"), float("nan")])
def test_invalid_values(value):
    assert collect(value).observations == []


def test_invalid_provider():
    assert collect(-1., valid=False).observations == []


def rows(count=12):
    result = []
    obs, = collect().observations
    for i in range(count):
        when = HOUR + timedelta(minutes=5*i)
        payload = obs.model_dump(mode="json")
        payload.update(observed_at=when.isoformat(), provider_timestamp=provider_clock(when).isoformat(), value=float(i-5))
        result.append(dict(id=i+1, source="air_pollution", cell_id="ministry:17:101:PM10:"+quote("µg/m³", safe=""),
                           observed_at=when, ingested_at=when+timedelta(seconds=10), payload=payload))
    return result


def aggregate(data, **kwargs):
    return aggregate_hour(data, station_id="17", channel_id="101", pollutant="PM10", measurement_unit="µg/m³",
                          hour_start=HOUR, as_of=kwargs.pop("as_of", HOUR+timedelta(hours=1)), **kwargs)


@pytest.mark.parametrize("month", [1, 7])
def test_fixed_clock(month):
    t = datetime(2026, month, 1, 23, tzinfo=timezone.utc)
    p = provider_clock(t)
    assert (p.day, p.hour, p.utcoffset()) == (2, 1, timedelta(hours=2))


def test_month_rollover():
    assert provider_clock("2026-01-31T23:00:00Z").month == 2


def test_provider_observation_hour_contract():
    label = provider_hour_for_observation(
        "2026-07-31T22:15:00Z", "2026-08-01T00:15:00+02:00",
    )
    assert label.isoformat() == "2026-08-01T00:00:00+02:00"


@pytest.mark.parametrize("provider_timestamp", [
    "2026-08-01T01:15:00+03:00",
    "2026-08-01T00:20:00+02:00",
])
def test_provider_observation_hour_rejects_clock_mismatch(provider_timestamp):
    with pytest.raises(ValueError):
        provider_hour_for_observation(
            "2026-07-31T22:15:00Z", provider_timestamp,
        )


@pytest.mark.parametrize("count,status", [(12, "ready"), (9, "ready"), (8, "insufficient_data"), (0, "insufficient_data")])
def test_completeness(count, status):
    data = rows(count)
    original = deepcopy(data)
    result = aggregate(data)
    assert result["status"] == status and result["sample_count"] == count
    assert result["mean"] == (pytest.approx((count-1)/2-5) if count >= 9 else None)
    assert result["aggregation_policy"] == AGGREGATION_POLICY
    assert result["quality_policy"] == LIVE_QUALITY_POLICY
    assert result["provider_hour"] == "2026-07-01T10:00:00+02:00"
    assert len(result["contributing_observations"]) == count
    assert data == original


def test_completed_boundary():
    assert aggregate(rows(), as_of=HOUR+timedelta(minutes=59, seconds=59))["mean"] is None
    assert aggregate(rows())["status"] == "ready"


def test_off_grid_and_missed_poll():
    data = rows(9)
    data[0]["observed_at"] += timedelta(seconds=1)
    result = aggregate(data)
    assert result["status"] == "insufficient_data" and result["sample_count"] == 8
    assert result["flags"][0]["reason"] == "off_grid"


def test_first_seen_even_when_input_reversed():
    data = rows(9)
    revision = deepcopy(data[0])
    revision.update(id=100, ingested_at=HOUR+timedelta(minutes=10))
    revision["payload"]["value"] = 999
    result = aggregate([revision]+list(reversed(data)))
    assert result["mean"] == -1.
    assert result["sample_count"] == 9
    assert {r["id"] for r in result["contributing_observations"]} == set(range(1, 10))
    assert result["flags"][0]["reason"] == "duplicate_first_seen"


@pytest.mark.parametrize("changes,reason", [
    ({"unit_source": "metadata_fallback", "measurement_unit": None}, "unverified_measurement_unit"),
    ({"unit_source": "unknown"}, "unverified_measurement_unit"),
    ({"valid": False}, "invalid_measurement"),
    ({"value": -9999}, "invalid_measurement"),
    ({"value": float("nan")}, "invalid_measurement"),
    ({"quality_policy": None}, "unverified_quality_policy"),
    ({"provider_timestamp": "2026-07-01T11:00:00+03:00"}, "provider_clock_mismatch"),
])
def test_unusable_input(changes, reason):
    data = rows(9)
    data[0]["payload"].update(changes)
    result = aggregate(data)
    assert result["status"] == "insufficient_data"
    assert result["flags"][0]["reason"] == reason


def test_late_arrival_and_series_isolation():
    data = rows(9)
    data[0]["ingested_at"] = HOUR+timedelta(hours=2)
    assert aggregate(data)["sample_count"] == 8
    assert aggregate(data, as_of=HOUR+timedelta(hours=2))["status"] == "ready"
    data[1]["payload"]["provider_station_id"] = "18"
    assert aggregate(data)["sample_count"] == 7


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        provider_clock(datetime(2026, 1, 1))


def test_first_seen_ineligible_row_is_not_replaced_by_later_eligible_revision():
    data = rows(9)
    revision = deepcopy(data[0])
    revision.update(id=100, ingested_at=HOUR+timedelta(minutes=30))
    data[0]["payload"]["quality_policy"] = None
    result = aggregate([revision]+data)
    assert result["sample_count"] == 8


@pytest.mark.parametrize("field,value", [("provider_channel_id", "102"), ("pollutant", "SO2"),
                                          ("unit", "ppb")])
def test_exact_series_only(field, value):
    data = rows(9)
    data[0]["payload"][field] = value
    assert aggregate(data)["sample_count"] == 8


def test_no_db_or_network_imports():
    import ast
    from pathlib import Path
    tree = ast.parse(Path("ecoguard/detectors/air_pollution/hourly.py").read_text(encoding="utf-8"))
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert imports == ["datetime", "urllib.parse", "ecoguard.shared.air_quality_schemas"]


def test_reading_unit_original_text_preserved():
    obs, = collect(unit=" ug/m3 ").observations
    assert obs.reading_unit == " ug/m3 " and obs.measurement_unit == "µg/m³"


def test_unknown_unit_identity_does_not_shadow_reading_unit_identity():
    data = rows(9)
    unknown = deepcopy(data[0])
    unknown.update(id=0, cell_id="ministry:17:101:PM10:__unknown_unit__")
    unknown["payload"].update(unit=None, measurement_unit=None, unit_source="unknown")
    assert aggregate([unknown]+data)["sample_count"] == 9
