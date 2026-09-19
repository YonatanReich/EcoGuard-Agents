"""Persisted-observation to shared flood signal integration tests."""

from datetime import datetime, timedelta, timezone

from ecoguard.detectors.flood import observation_processing
from ecoguard.detectors.flood.station_rules import HYDROMETRIC_SOURCE


NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0040-c0012"


def _row(identifier: int, at: datetime, discharge: float) -> dict:
    return {
        "id": identifier,
        "source": HYDROMETRIC_SOURCE,
        "cell_id": CELL,
        "observed_at": at,
        "ingested_at": NOW,
        "payload": {
            "stations": [{
                "source_station_id": 50,
                "discharge_m3s": discharge,
                "latitude": 32.0,
                "longitude": 34.8,
                "flow_threshold_status": "complete_thresholds",
                "flow_threshold_2y_m3s": 10.0,
                "flow_threshold_5y_m3s": 20.0,
                "flow_threshold_10y_m3s": 30.0,
                "flow_threshold_20y_m3s": 40.0,
                "flow_threshold_50y_m3s": 50.0,
                "flow_threshold_100y_m3s": 60.0,
            }]
        },
    }


def test_detect_new_returns_shared_signals(monkeypatch):
    newest = _row(2, NOW, 42.0)
    window = [_row(1, NOW - timedelta(minutes=10), 31.0), newest]
    calls = []

    monkeypatch.setattr(
        observation_processing,
        "last_success_at",
        lambda _: NOW - timedelta(minutes=30),
    )
    monkeypatch.setattr(observation_processing, "log_start", lambda _: 7)
    monkeypatch.setattr(observation_processing, "log_finish", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(
        observation_processing,
        "read_observations_batch",
        lambda *args, **kwargs: [newest] if kwargs["after_id"] == 0 else [],
    )
    monkeypatch.setattr(observation_processing, "load_window", lambda *args, **kwargs: window)
    monkeypatch.setattr(observation_processing, "load_stream_ids", lambda station_ids: {50: 701})

    result = observation_processing.detect_new(at=NOW)

    assert len(result) == 1
    assert result[0].evidence["stream_id"] == 701
    assert calls[-1][1]["status"] == "ok"
