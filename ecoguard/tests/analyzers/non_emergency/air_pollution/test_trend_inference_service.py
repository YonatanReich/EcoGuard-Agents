from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import joblib
import numpy as np

from ecoguard.analyzers.non_emergency.air_pollution.trend_inference_service import (
    AirPollutionTrendInferenceService,
)
from ecoguard.shared.air_pollution_trend_model import (
    FinalSGDModelBundle,
    IdentityVocabulary,
)
from ecoguard.shared.air_pollution_trend_policy import (
    LOCKED_TREND_SGD_CONFIGURATIONS,
    TREND_FINAL_ARTIFACT_VERSION,
    TREND_LABELS,
    TREND_MINIMUM_HISTORY_COVERAGE,
    TREND_PREPROCESSING_VERSION,
)
from ecoguard.shared.air_pollution_history import AirPollutionSeriesIdentity
from ecoguard.shared.air_pollution_trend_features import (
    FEATURE_COLUMNS,
    TREND_FEATURE_POLICY_VERSION,
)
from ecoguard.shared.air_quality_schemas import AirQualityObservation
from ecoguard.tests.analyzers.non_emergency.air_pollution.test_event_analyzer import (
    GENERATED_AT,
    OBSERVED_AT,
    _candidate,
)


class FakeScaler:
    def transform(self, values):
        return values


class FakeClassifier:
    classes_ = np.arange(3)

    def predict_proba(self, values):
        return np.repeat(np.asarray([[0.1, 0.2, 0.7]]), values.shape[0], axis=0)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_artifact(directory, *, station_id="42", channel_id="7001"):
    identity = AirPollutionSeriesIdentity(station_id, channel_id, "NO2")
    vocabulary = IdentityVocabulary.fit([identity])
    bundle = FinalSGDModelBundle(
        artifact_version=TREND_FINAL_ARTIFACT_VERSION,
        model_version="air-pollution-trend-sgd-no2-training-2021-2023-v1",
        pollutant="NO2",
        training_start="2021-01-01T00:00:00+02:00",
        training_end="2024-01-01T00:00:00+02:00",
        feature_policy_version=TREND_FEATURE_POLICY_VERSION,
        preprocessing_version=TREND_PREPROCESSING_VERSION,
        epsilon_policy={"version": "training-only-epsilon-v1", "epsilon": 1.0},
        configuration=asdict(LOCKED_TREND_SGD_CONFIGURATIONS["NO2"]),
        feature_columns=tuple(FEATURE_COLUMNS),
        labels=tuple(TREND_LABELS),
        scaler=FakeScaler(),
        identity_vocabulary=vocabulary,
        classifier=FakeClassifier(),
    )
    artifact = directory / "no2.joblib"
    joblib.dump(bundle, artifact)
    manifest = {
        "artifact_version": TREND_FINAL_ARTIFACT_VERSION,
        "feature_policy_version": TREND_FEATURE_POLICY_VERSION,
        "preprocessing_version": TREND_PREPROCESSING_VERSION,
        "training_period": [bundle.training_start, bundle.training_end],
        "minimum_history_coverage": TREND_MINIMUM_HISTORY_COVERAGE,
        "pollutants_with_models": ["NO2", "O3", "PM2.5", "SO2"],
        "unavailable_pollutants": {"PM10": "no_accepted_model"},
        "models": {
            "NO2": {
                "path": artifact.name,
                "sha256": _sha256(artifact),
                "model_version": bundle.model_version,
                "configuration": bundle.configuration,
                "identity_vocabulary": {
                    "version": vocabulary.version,
                    "station_ids": list(vocabulary.station_ids),
                    "channel_ids": list(vocabulary.channel_ids),
                    "series_ids": [
                        {"station_id": station, "channel_id": channel}
                        for station, channel in vocabulary.series_ids
                    ],
                },
            }
        },
        "epsilon_policy": {"NO2": bundle.epsilon_policy},
        "outer_2024_accessed": False,
        "2025_accessed": False,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def _rows(count=25):
    rows = []
    first = OBSERVED_AT - timedelta(minutes=5 * (count - 1))
    for index in range(count):
        observed_at = first + timedelta(minutes=5 * index)
        observation = AirQualityObservation(
            pollutant="NO2",
            value=float(index + 1),
            unit="ppb",
            measurement_unit="ppb",
            unit_source="reading",
            reading_unit="ppb",
            quality_policy="ecoguard-provider-valid-signed-v1",
            provider_station_id="42",
            provider_channel_id="7001",
            location={"latitude": 32.1, "longitude": 34.8},
            observed_at=observed_at,
            provider_timestamp=observed_at.isoformat(),
        )
        rows.append({
            "id": index + 1,
            "source": "air_pollution",
            "cell_id": "unused-by-adapter",
            "observed_at": observed_at,
            "ingested_at": observed_at,
            "payload": observation.model_dump(mode="json"),
            "latitude": 32.1,
            "longitude": 34.8,
        })
    rows[-1]["payload"]["value"] = 21.0
    return rows


def _candidate_with_pollutant(pollutant):
    payload = _candidate().model_dump(round_trip=True)
    payload["anomaly"]["pollutant"] = pollutant
    payload["anomaly"]["live_observation"]["pollutant"] = pollutant
    payload["anomaly"]["baseline_evidence"]["identity"]["pollutant"] = pollutant
    return type(_candidate()).model_validate(payload)


def test_live_trend_inference_reuses_causal_features_and_returns_provenance(tmp_path):
    _write_artifact(tmp_path)
    calls = []

    def reader(**kwargs):
        calls.append(kwargs)
        return _rows()

    result = AirPollutionTrendInferenceService(
        artifact_directory=tmp_path,
        history_reader=reader,
        clock=lambda: GENERATED_AT,
    ).predict(_candidate())

    assert result.status == "success"
    assert result.result.trend == "RISING"
    assert result.result.confidence == 0.7
    assert result.result.probabilities == {
        "FALLING": 0.1,
        "STABLE": 0.2,
        "RISING": 0.7,
    }
    assert result.result.horizon_minutes == 30
    assert result.result.as_of == OBSERVED_AT
    assert result.result.station_id == "42"
    assert result.result.channel_id == "7001"
    assert result.result.feature_policy_version == TREND_FEATURE_POLICY_VERSION
    assert result.evidence[0].source_type == "sgd_logistic_trend_model"
    assert calls == [{
        "station_id": "42",
        "channel_id": "7001",
        "pollutant": "NO2",
        "unit": "ppb",
        "prediction_time": OBSERVED_AT,
        "lookback_minutes": 120,
    }]


def test_pm10_unsupported_missing_history_and_identity_fail_closed(tmp_path):
    service = AirPollutionTrendInferenceService(
        artifact_directory=tmp_path,
        history_reader=lambda **kwargs: [],
        clock=lambda: GENERATED_AT,
    )
    assert service.predict(_candidate_with_pollutant("PM10")).unavailable_reason == (
        "pm10_no_accepted_model"
    )
    assert service.predict(_candidate_with_pollutant("CO")).unavailable_reason == (
        "unsupported_pollutant"
    )
    assert service.predict(_candidate()).unavailable_reason == "trend_artifact_missing"

    _write_artifact(tmp_path)
    insufficient = service.predict(_candidate())
    assert insufficient.unavailable_reason == "insufficient_causal_history"

    other_directory = tmp_path / "other"
    other_directory.mkdir()
    _write_artifact(other_directory, station_id="999", channel_id="888")
    mismatch = AirPollutionTrendInferenceService(
        artifact_directory=other_directory,
        history_reader=lambda **kwargs: _rows(),
        clock=lambda: GENERATED_AT,
    ).predict(_candidate())
    assert mismatch.unavailable_reason == "identity_model_mismatch"
