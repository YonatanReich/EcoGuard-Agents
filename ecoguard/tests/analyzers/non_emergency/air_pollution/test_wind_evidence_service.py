"""Persisted-first Air Pollution wind selection tests."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ecoguard.analyzers.non_emergency.air_pollution.wind_evidence_service import (
    PersistedFirstWindEvidenceService,
)
from ecoguard.detectors.air_pollution.schemas import GeographicCoordinate
from ecoguard.tests.analyzers.non_emergency.air_pollution.test_event_analyzer import (
    GENERATED_AT,
    OBSERVED_AT,
    POINT,
    _wind,
)


def _stored_weather(*, observed_at=OBSERVED_AT - timedelta(minutes=10)):
    return {
        "source": "weather",
        "cell_id": "weather-grid:1",
        "observed_at": observed_at,
        "latitude": POINT["latitude"] + 0.01,
        "longitude": POINT["longitude"] + 0.01,
        "distance_m": 1400.0,
        "payload": {
            "wind_speed_10m": 18.0,
            "wind_direction_10m": 270.0,
            "wind_gusts_10m": 25.2,
        },
    }


def test_fresh_db_wind_wins_without_live_or_write():
    live = Mock()
    writer = Mock()
    reader = Mock(return_value=_stored_weather())
    service = PersistedFirstWindEvidenceService(
        live,
        reader=reader,
        writer=writer,
        clock=lambda: GENERATED_AT,
    )

    selection = service.select_wind_evidence(
        analysis_coordinates=POINT,
        anomaly_observed_at=OBSERVED_AT,
        maximum_observation_age_seconds=1800.0,
    )

    evidence = selection.wind_evidence
    assert evidence.provider == "Open-Meteo"
    assert evidence.source_type == "model_forecast"
    assert evidence.wind_speed_mps == 5.0
    assert evidence.wind_from_direction_deg == 270.0
    assert evidence.wind_valid_at == OBSERVED_AT - timedelta(minutes=10)
    assert evidence.metadata["repository_source"] == "weather"
    reader.assert_called_once_with(
        POINT["latitude"],
        POINT["longitude"],
        at=OBSERVED_AT,
        maximum_age_seconds=1800.0,
        sources=("weather", "ims_wind"),
    )
    live.select_wind_evidence.assert_not_called()
    writer.assert_not_called()


def test_stale_db_wind_uses_targeted_live_observation_and_persists_it():
    live = Mock()
    live.select_wind_evidence.return_value = SimpleNamespace(wind_evidence=_wind())
    writer = Mock(return_value=1)
    service = PersistedFirstWindEvidenceService(
        live,
        reader=Mock(return_value=_stored_weather(
            observed_at=OBSERVED_AT - timedelta(hours=2)
        )),
        writer=writer,
        clock=lambda: GENERATED_AT,
    )

    selection = service.select_wind_evidence(
        analysis_coordinates=POINT,
        anomaly_observed_at=OBSERVED_AT,
        maximum_observation_age_seconds=1800.0,
    )

    assert selection.wind_evidence.provider == "IMS"
    live.select_wind_evidence.assert_called_once_with(
        analysis_coordinates=GeographicCoordinate.model_validate(POINT),
        anomaly_observed_at=OBSERVED_AT,
        maximum_observation_age_seconds=1800.0,
        alternative_limit=3,
    )
    source, records = writer.call_args.args
    assert source == "ims_wind"
    assert records[0]["cell_id"] == "ims:10"
    assert records[0]["observed_at"] == OBSERVED_AT
    assert records[0]["payload"]["wind_speed_unit"] == "m/s"
    assert records[0]["payload"]["wind_direction_10m"] == 270.0


def test_live_failure_is_fail_closed_and_writes_nothing():
    live = Mock()
    live.select_wind_evidence.side_effect = RuntimeError("provider unavailable")
    writer = Mock()
    service = PersistedFirstWindEvidenceService(
        live,
        reader=Mock(return_value=None),
        writer=writer,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.select_wind_evidence(
            analysis_coordinates=POINT,
            anomaly_observed_at=OBSERVED_AT,
            maximum_observation_age_seconds=1800.0,
        )

    writer.assert_not_called()


def test_live_persistence_failure_prevents_wind_use():
    live = Mock()
    live.select_wind_evidence.return_value = SimpleNamespace(wind_evidence=_wind())
    writer = Mock(side_effect=RuntimeError("database unavailable"))
    service = PersistedFirstWindEvidenceService(
        live,
        reader=Mock(return_value=None),
        writer=writer,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.select_wind_evidence(
            analysis_coordinates=POINT,
            anomaly_observed_at=OBSERVED_AT,
            maximum_observation_age_seconds=1800.0,
        )
