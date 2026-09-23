"""Focused smoke validation against the generated final Trend ML artifacts."""

from unittest.mock import Mock

import pytest

from ecoguard.analyzers.air_pollution.trend_inference_service import (
    DEFAULT_ARTIFACT_DIRECTORY,
    AirPollutionTrendInferenceService,
)
from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.shared.air_pollution_trend_model import (
    FinalSGDModelBundle,
    IdentityVocabulary,
)
from ecoguard.tests.analyzers.air_pollution.test_event_analyzer import (
    GENERATED_AT,
    _candidate,
)
from ecoguard.tests.analyzers.air_pollution.test_trend_inference_service import (
    _candidate_with_pollutant,
    _rows,
)

NO2_STATION_ID = "1"
NO2_CHANNEL_ID = "4"


def test_serialized_contract_classes_live_in_the_shared_module():
    """Artifacts on disk were pickled against these classes; the paths must hold.

    This also compared them against the phase2b training script, which was a
    one-off experiment with no production importer and has been removed.
    """
    assert FinalSGDModelBundle.__module__ == (
        "ecoguard.shared.air_pollution_trend_model"
    )
    assert IdentityVocabulary.__module__ == "ecoguard.shared.air_pollution_trend_model"


def _real_no2_candidate() -> PollutionCorrelationCandidate:
    payload = _candidate().model_dump(round_trip=True)
    anomaly = payload["anomaly"]
    anomaly["detection_id"] = "air-pollution:real-artifact-smoke:no2"
    anomaly["station_id"] = NO2_STATION_ID
    anomaly["channel_id"] = NO2_CHANNEL_ID
    anomaly["live_observation"]["station_id"] = NO2_STATION_ID
    anomaly["live_observation"]["channel_id"] = NO2_CHANNEL_ID
    anomaly["baseline_evidence"]["identity"]["station_id"] = NO2_STATION_ID
    anomaly["baseline_evidence"]["identity"]["channel_id"] = NO2_CHANNEL_ID
    return PollutionCorrelationCandidate.model_validate(payload)


def _controlled_no2_history():
    rows = _rows(count=25)
    for row in rows:
        row["payload"]["provider_station_id"] = NO2_STATION_ID
        row["payload"]["provider_channel_id"] = NO2_CHANNEL_ID
    return rows


def test_real_no2_artifact_loads_validates_and_predicts_from_synthetic_history():
    calls = []

    def controlled_reader(**kwargs):
        calls.append(kwargs)
        return _controlled_no2_history()

    result = AirPollutionTrendInferenceService(
        artifact_directory=DEFAULT_ARTIFACT_DIRECTORY,
        history_reader=controlled_reader,
        clock=lambda: GENERATED_AT,
    ).predict(_real_no2_candidate())

    assert result.status == "success", result.unavailable_reason
    prediction = result.result
    assert prediction is not None
    assert prediction.pollutant == "NO2"
    assert prediction.station_id == NO2_STATION_ID
    assert prediction.channel_id == NO2_CHANNEL_ID
    assert prediction.trend in {"RISING", "STABLE", "FALLING"}
    assert set(prediction.probabilities) == {"RISING", "STABLE", "FALLING"}
    assert sum(prediction.probabilities.values()) == pytest.approx(1.0)
    assert prediction.confidence == pytest.approx(
        prediction.probabilities[prediction.trend]
    )
    assert prediction.horizon_minutes == 30
    assert result.evidence[0].metadata["model_sha256"]
    assert calls == [
        {
            "station_id": NO2_STATION_ID,
            "channel_id": NO2_CHANNEL_ID,
            "pollutant": "NO2",
            "unit": "ppb",
            "prediction_time": prediction.as_of,
            "lookback_minutes": 120,
        }
    ]
    print(
        "real NO2 artifact prediction:",
        prediction.trend,
        prediction.confidence,
        prediction.probabilities,
    )


def test_pm10_returns_no_accepted_model_without_loading_artifacts():
    history_reader = Mock(side_effect=AssertionError("history must not be read"))
    service = AirPollutionTrendInferenceService(
        artifact_directory=DEFAULT_ARTIFACT_DIRECTORY,
        history_reader=history_reader,
        clock=lambda: GENERATED_AT,
    )
    service._load_bundle = Mock(side_effect=AssertionError("artifact must not load"))

    result = service.predict(_candidate_with_pollutant("PM10"))

    assert result.status == "unavailable"
    assert result.unavailable_reason == "pm10_no_accepted_model"
    service._load_bundle.assert_not_called()
    history_reader.assert_not_called()
