"""Offline provider-to-shared-repository contract and scheduler checks."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from ecoguard.collection.pollution.collector import AirPollutionCollector
from ecoguard.database.repositories import observations as repository
from ecoguard.tests.collection.test_base_collector import _Recorder
from ecoguard.tests.collection.pollution.test_ministry_air_quality_client import FakeSession, channel, routes_for, station
from ecoguard.shared.ministry_air_quality_client import MinistryAirQualityClient

NOW = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)


def collector(readings, **kwargs):
    session = FakeSession(routes_for(readings, **kwargs))
    client = MinistryAirQualityClient(session=session, clock=lambda: NOW)
    return AirPollutionCollector(client, clock=lambda: NOW)


def test_provider_measurement_maps_to_shared_record_and_postgis_point():
    record, = collector({17: [channel("NOX", 20.0, unit="ppb")]}).fetch()
    assert record["cell_id"] == "ministry:17:101:NOx:ppb"
    assert record["observed_at"] == datetime(2026, 9, 7, 8, 15, tzinfo=timezone.utc)
    assert (record["latitude"], record["longitude"]) == (32.0853, 34.7818)
    payload = record["payload"]
    assert payload["provider_station_id"] == "17"
    assert payload["provider_channel_id"] == "101"
    assert payload["provider_pollutant_id"] == "1101"
    assert (payload["pollutant"], payload["value"], payload["unit"]) == ("NOx", 20.0, "ppb")
    assert payload["provider_unit"] == "ppb"
    assert payload["measurement_unit"] == "ppb"
    assert payload["unit_source"] == "reading"
    assert payload["reading_unit"] == "ppb"
    assert payload["quality_policy"] == "ecoguard-provider-valid-signed-v1"
    assert payload["provider_timestamp"] == "2026-09-07T10:15:00+02:00"
    assert payload["valid"] is True
    assert payload["provider_status_id"] == "1"
    assert payload["provider_status"] == "Normal"
    assert payload["quality_control"] == "preliminary_unvalidated"
    assert payload["provider"] == "israel_ministry_environment_air_monitoring"
    json.dumps(payload, allow_nan=False)
    row = repository._row(AirPollutionCollector.source, record, NOW)
    assert row["source"] == "air_pollution"
    assert row["ingested_at"] == NOW
    assert row["location"].srid == 4326
    assert str(row["location"]) == "POINT(34.7818 32.0853)"


def test_signed_unknown_unit_reaches_shared_record_without_assumed_unit():
    record, = collector({17: [channel("PM10", -1.2, unit=None)]}).fetch()
    assert record["payload"]["value"] == -1.2
    assert record["payload"]["unit"] is None
    assert record["payload"]["measurement_unit"] is None
    assert record["payload"]["unit_source"] == "unknown"
    assert record["cell_id"] == "ministry:17:101:PM10:__unknown_unit__"


def test_metadata_fallback_is_preserved_but_not_claimed_as_actual_unit():
    monitors = [{"channelId": 101, "name": "NO2", "units": "ppb", "active": True}]
    record, = collector({17: [channel("NO2", 1.2, unit=None)]}, stations=[station(monitors=monitors)]).fetch()
    assert record["payload"]["unit"] == "ppb"
    assert record["payload"]["metadata_unit"] == "ppb"
    assert record["payload"]["measurement_unit"] is None
    assert record["payload"]["unit_source"] == "metadata_fallback"


@pytest.mark.parametrize("changes", [
    {"valid": False}, {"value": -9999.0}, {"value": float("nan")},
    {"active": False}, {"state": "Calib", "status": None, "valid": False},
    {"datetime": "2026-09-07T10:15:00"},
    {"datetime": "2026-09-07T12:15:00+02:00"},
])
def test_invalid_naive_and_future_readings_are_excluded(changes):
    reading = {**channel("PM10", 10.0), **changes}
    assert collector({17: [reading]}).fetch() == []


def test_inactive_station_is_excluded():
    assert collector({17: [channel("PM10", 10.0)]},
                     stations=[{**station(), "active": False}]).fetch() == []


def test_station_channel_pollutant_and_unit_are_distinct_stable_series():
    readings = {17: [channel("PM10", 10.0), channel("NO2", 2.0, unit="ppb"),
                     channel("PM10", 11.0, channel_id=102),
                     channel("PM10", 12.0, unit="ug/m3")],
                18: [channel("PM10", 13.0)]}
    instance = collector(readings)
    records = instance.fetch()
    assert len(records) == len({record["cell_id"] for record in records}) == 5
    assert records == instance.fetch()
    assert {r["payload"]["provider_station_id"] for r in records} == {"17", "18"}


def test_run_uses_shared_audit_and_repository(monkeypatch):
    recorder = _Recorder(monkeypatch)
    collector({17: [channel("CO", 1.0)]}).run()
    assert recorder.lock_name == "collect_air_pollution"
    assert recorder.upserted[0] == "air_pollution"
    assert recorder.finished == [(7, {"status": "ok", "rows_written": 1})]


def test_output_reaches_shared_insert_with_conflict_ignore(monkeypatch):
    records = collector({17: [channel("CO", 1.0)]}).fetch()
    statements = []
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [1]))
        def commit(self): pass
    monkeypatch.setattr(repository, "Session", Session)
    assert repository.upsert_observations("air_pollution", records) == 1
    compiled = statements[0].compile(dialect=postgresql.dialect())
    assert "ON CONFLICT ON CONSTRAINT observations_identity DO NOTHING" in str(compiled)
    assert compiled.params["payload_m0"] == records[0]["payload"]


def test_credentials_absent_from_output_logs_and_audit(monkeypatch, caplog):
    instance = collector({17: [channel("CO", 1.0)]})
    serialized = json.dumps(instance.fetch(), default=str)
    assert "guest-api-token" not in serialized
    assert "access-cookie" not in serialized
    recorder = _Recorder(monkeypatch)
    def fail():
        raise RuntimeError("Authorization: JwtToken secret-test-credential")
    instance.client.collect_latest = fail
    instance.run()
    assert recorder.finished[0][1]["status"] == "failed"
    assert "secret-test-credential" not in caplog.text + str(recorder.finished)
    assert recorder.upserted is None


def test_failed_provider_result_is_a_failed_audit(monkeypatch):
    recorder = _Recorder(monkeypatch)
    instance = collector({17: [channel("CO", 1.0)]})
    from ecoguard.tests.collection.pollution.test_ministry_air_quality_client import FakeResponse
    instance.client.session.routes["regions/data/latest"] = [FakeResponse({}, 503)]
    instance.run()
    assert recorder.finished[0][1]["status"] == "failed"
    assert recorder.upserted is None


def test_scheduler_registers_guest_collector_without_starting():
    from ecoguard.scheduler import scheduler, unconfigured
    job = scheduler.get_job("collect_air_pollution")
    assert isinstance(job.func.__self__, AirPollutionCollector)
    assert job.trigger.interval.total_seconds() == 300
    assert job.max_instances == 1 and job.coalesce is True
    assert unconfigured("air_pollution") == []
    assert scheduler.running is False
