"""Verify the historical input, registration and dedicated-schema requirement."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from ecoguard.api.scenario import SCENARIOS, scenario_catalog
from ecoguard.collectors.earthquake.gsi import GsiEarthquake
from ecoguard.demo.scenarios import earthquake_demo as demo
from ecoguard.detectors.earthquake.observation_processing import signals_from_observations

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def test_embedded_historical_record_reaches_the_real_detector():
    source, cell, observed, payload = demo.build_rows(NOW)[0]
    replay = GsiEarthquake.model_validate(payload)
    assert source == "gsi_earthquake"
    assert cell == "risk-05000m-r0071-c0018"
    assert observed == NOW - timedelta(minutes=5) == replay.observed_at
    assert replay.provider_event_id == "gsi198408240602"
    assert (replay.latitude, replay.longitude) == (32.65079498, 35.19147491)
    assert replay.magnitude == 5.347415924
    assert replay.depth_km == 12
    assert replay.raw["event_type"] == "earthquake"
    assert replay.raw["magnitude_type"] == "Md"
    assert replay.raw["demo_replay"]["historical_observed_at"] == "1984-08-24T06:02:25.358+00:00"
    signals = signals_from_observations([
        {"source": source, "cell_id": cell, "observed_at": observed, "payload": payload}
    ])
    assert len(signals) == 1
    assert signals[0].value == 5.347415924
    assert signals[0].evidence["earthquake"] == payload


@pytest.mark.parametrize("schema", ["public", "demo_a", "", 'earthquake_demo"; DROP SCHEMA public'])
def test_seed_rejects_every_other_schema_before_opening_a_session(monkeypatch, schema):
    session = MagicMock()
    monkeypatch.setattr(demo, "Session", session)
    with pytest.raises(ValueError, match="must be seeded into earthquake_demo"):
        demo.seed(schema, now=NOW)
    session.assert_not_called()


def test_seed_is_explicitly_qualified_even_when_live_search_path_is_active(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(demo, "Session", lambda: session)
    result = demo.seed("earthquake_demo", now=NOW)
    statement, values = session.__enter__.return_value.execute.call_args.args
    assert 'INSERT INTO "earthquake_demo".observations' in str(statement)
    assert "ST_MakePoint(:longitude, :latitude)" in str(statement)
    assert values["ingested_at"] == NOW
    assert values["observed_at"] == NOW - timedelta(minutes=5)
    assert json.loads(values["payload"])["provider_event_id"] == demo.EVENT_ID
    session.__enter__.return_value.commit.assert_called_once()
    assert result["observations"] == 1


def test_replay_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone"):
        demo.build_rows(NOW.replace(tzinfo=None))


def test_catalog_contains_the_historical_earthquake():
    assert SCENARIOS[demo.SCHEMA].endswith(".earthquake_demo")
    item = next(item for item in scenario_catalog()["scenarios"] if item["id"] == demo.SCHEMA)
    assert item["event_count"] == 1
    assert item["events"][0]["hazard"] == "earthquake"
    assert item["events"][0]["latitude"] == demo.EPICENTRE[0]
    assert item["events"][0]["longitude"] == demo.EPICENTRE[1]
