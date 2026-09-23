"""Is this pollution reading rising, falling or steady?

Runs the trained model over the reading's recent history. The model file is
fingerprinted against what was approved, so a swapped artifact is refused
rather than quietly used.

When history is missing or the model does not apply, it says so instead of
guessing."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from ecoguard.analyzers.air_pollution.event_analysis_schemas import (
    AirPollutionTrendPrediction,
    AnalysisComponent,
)
from ecoguard.analyzers.air_pollution.transport_schemas import (
    TransportEvidenceReference,
)
from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.detectors.air_pollution.observation_processing import (
    PersistedObservationAdapterError,
    air_quality_observation_from_row,
)
from ecoguard.paths import GENERATED
from ecoguard.shared.air_pollution_history import (
    AirPollutionSeriesIdentity,
    HistoricalAirPollutionObservation,
)
from ecoguard.shared.air_pollution_trend_model import FinalSGDModelBundle
from ecoguard.shared.air_pollution_trend_policy import (
    APPROVED_TREND_MODEL_POLLUTANTS,
    LOCKED_TREND_SGD_CONFIGURATIONS,
    SUPPORTED_TREND_POLLUTANTS,
    TREND_FINAL_ARTIFACT_VERSION,
    TREND_FINAL_TRAINING_END,
    TREND_FINAL_TRAINING_START,
    TREND_HORIZON_MINUTES,
    TREND_LABELS,
    TREND_MINIMUM_HISTORY_COVERAGE,
    TREND_PREPROCESSING_VERSION,
    UNAVAILABLE_TREND_POLLUTANTS,
)
from ecoguard.shared.air_pollution_trend_features import (
    FEATURE_COLUMNS,
    LOOKBACK_MINUTES,
    TREND_FEATURE_POLICY_VERSION,
    build_causal_features,
)

DEFAULT_ARTIFACT_DIRECTORY = (
    GENERATED / "ml" / "air_pollution_trend" / "final"
)
HistoryReader = Callable[..., list[dict[str, Any]]]


def _default_history_reader(**kwargs) -> list[dict[str, Any]]:
    """The reader used when a caller does not supply one."""
    from ecoguard.database.repositories.observations import (
        read_air_pollution_series_history,
    )

    return read_air_pollution_series_history(**kwargs)


def _sha256(path: Path) -> str:
    """A fingerprint of a file, so a swapped model artifact is noticed."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class _Unavailable(RuntimeError):
    def __init__(self, reason: str):
        """Carry the reason a prediction cannot be made."""
        super().__init__(reason)
        self.reason = reason


class AirPollutionTrendInferenceService:
    """Load approved bundles and infer without detecting, routing, or persisting."""

    def __init__(
        self,
        *,
        artifact_directory: Path = DEFAULT_ARTIFACT_DIRECTORY,
        history_reader: HistoryReader = _default_history_reader,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """Build the service. The history reader is injectable for testing."""
        self._artifact_directory = Path(artifact_directory)
        self._history_reader = history_reader
        self._clock = clock
        self._loaded: dict[str, tuple[FinalSGDModelBundle, dict[str, Any], str]] = {}

    def predict(
        self, candidate: PollutionCorrelationCandidate
    ) -> AnalysisComponent[AirPollutionTrendPrediction]:
        """Where this reading is heading, or why that cannot be said."""
        validated = PollutionCorrelationCandidate.model_validate(
            candidate.model_dump(round_trip=True)
        )
        pollutant = validated.anomaly.pollutant
        if pollutant in UNAVAILABLE_TREND_POLLUTANTS:
            return self._unavailable(
                f"{pollutant.lower()}_{UNAVAILABLE_TREND_POLLUTANTS[pollutant]}"
            )
        if pollutant not in SUPPORTED_TREND_POLLUTANTS:
            return self._unavailable("unsupported_pollutant")
        try:
            return self._predict(validated)
        except _Unavailable as error:
            return self._unavailable(error.reason)
        except Exception:
            return self._unavailable("trend_inference_failure")

    @staticmethod
    def _unavailable(
        reason: str,
    ) -> AnalysisComponent[AirPollutionTrendPrediction]:
        """A result saying no prediction is available, and why."""
        return AnalysisComponent[AirPollutionTrendPrediction](
            status="unavailable",
            unavailable_reason=reason,
        )

    def _predict(
        self, candidate: PollutionCorrelationCandidate
    ) -> AnalysisComponent[AirPollutionTrendPrediction]:
        """Run the model over one reading's recent history."""
        anomaly = candidate.anomaly
        bundle, model_record, model_sha256 = self._load_bundle(anomaly.pollutant)
        identity = AirPollutionSeriesIdentity(
            anomaly.station_id, anomaly.channel_id, anomaly.pollutant
        )
        vocabulary = bundle.identity_vocabulary
        if (
            identity.station_id not in vocabulary.station_ids
            or identity.channel_id not in vocabulary.channel_ids
            or (identity.station_id, identity.channel_id) not in vocabulary.series_ids
        ):
            raise _Unavailable("identity_model_mismatch")

        rows = self._history_reader(
            station_id=anomaly.station_id,
            channel_id=anomaly.channel_id,
            pollutant=anomaly.pollutant,
            unit=anomaly.unit,
            prediction_time=anomaly.observed_at,
            lookback_minutes=LOOKBACK_MINUTES,
        )
        observations = self._validated_history(rows, identity, anomaly.unit)
        by_time = {item.observed_at: item for item in observations}
        if len(by_time) != len(observations):
            raise _Unavailable("trend_inference_failure")
        current = by_time.get(anomaly.observed_at)
        if current is None or current.value != anomaly.value:
            raise _Unavailable("insufficient_causal_history")
        try:
            features = build_causal_features(observations, anomaly.observed_at)
        except ValueError:
            raise _Unavailable("insufficient_causal_history") from None
        minimum_coverage = float(model_record["minimum_history_coverage"])
        coverage = features["coverage_ratio_120m"]
        if coverage is None or coverage < minimum_coverage:
            raise _Unavailable("insufficient_causal_history")

        values = np.asarray(
            [[np.nan if features[name] is None else features[name] for name in FEATURE_COLUMNS]],
            dtype=np.float64,
        )
        probabilities = bundle.predict_proba(values, identity)
        if probabilities.shape != (1, 3) or not np.isfinite(probabilities).all():
            raise _Unavailable("trend_inference_failure")
        row = probabilities[0]
        if any(value < 0 or value > 1 for value in row) or not math.isclose(
            float(row.sum()), 1.0, abs_tol=1e-6
        ):
            raise _Unavailable("trend_inference_failure")
        winning_index = int(np.argmax(row))
        trend = TREND_LABELS[winning_index]
        issued_at = self._clock()
        if issued_at.tzinfo is None or issued_at.utcoffset() is None:
            raise _Unavailable("trend_inference_failure")
        issued_at = issued_at.astimezone(timezone.utc)
        epsilon_version = str(bundle.epsilon_policy["version"])
        result = AirPollutionTrendPrediction(
            trend=trend,
            confidence=float(row[winning_index]),
            probabilities={
                label: float(row[index])
                for index, label in enumerate(TREND_LABELS)
            },
            pollutant=identity.pollutant,
            station_id=identity.station_id,
            channel_id=identity.channel_id,
            unit=anomaly.unit,
            issued_at=issued_at,
            as_of=anomaly.observed_at,
            model_version=bundle.model_version,
            artifact_version=bundle.artifact_version,
            feature_policy_version=bundle.feature_policy_version,
            preprocessing_version=bundle.preprocessing_version,
            epsilon_policy_version=epsilon_version,
        )
        evidence_id = "trend-ml:" + hashlib.sha256(
            (
                f"{bundle.model_version}:{identity.station_id}:"
                f"{identity.channel_id}:{anomaly.observed_at.isoformat()}"
            ).encode("utf-8")
        ).hexdigest()
        return AnalysisComponent[AirPollutionTrendPrediction](
            status="success",
            result=result,
            evidence=[
                TransportEvidenceReference(
                    evidence_id=evidence_id,
                    source_name="EcoGuard Air Pollution Trend ML",
                    source_type="sgd_logistic_trend_model",
                    reference=str(model_record["path"]),
                    metadata={
                        "model_sha256": model_sha256,
                        "model_version": bundle.model_version,
                        "feature_policy_version": bundle.feature_policy_version,
                        "preprocessing_version": bundle.preprocessing_version,
                        "epsilon_policy_version": epsilon_version,
                        "horizon_minutes": TREND_HORIZON_MINUTES,
                    },
                )
            ],
        )

    @staticmethod
    def _validated_history(
        rows: list[dict[str, Any]],
        identity: AirPollutionSeriesIdentity,
        unit: str,
    ) -> list[HistoricalAirPollutionObservation]:
        """Reject a history that does not match the reading it is meant to describe."""
        observations = []
        try:
            for row in rows:
                item = air_quality_observation_from_row(row)
                if (
                    item.provider_station_id != identity.station_id
                    or item.provider_channel_id != identity.channel_id
                    or item.pollutant != identity.pollutant
                    or item.unit != unit
                ):
                    raise _Unavailable("identity_model_mismatch")
                observations.append(
                    HistoricalAirPollutionObservation(
                        identity=identity,
                        observed_at=item.observed_at,
                        value=item.value,
                        unit=unit,
                        provider_unit=item.reading_unit or item.metadata_unit or unit,
                    )
                )
        except PersistedObservationAdapterError:
            raise _Unavailable("trend_inference_failure") from None
        return sorted(observations, key=lambda item: item.observed_at)

    def _load_bundle(
        self, pollutant: str
    ) -> tuple[FinalSGDModelBundle, dict[str, Any], str]:
        """The trained model for one pollutant, loaded once and reused."""
        cached = self._loaded.get(pollutant)
        if cached is not None:
            return cached
        manifest_path = self._artifact_directory / "manifest.json"
        if not manifest_path.is_file():
            raise _Unavailable("trend_artifact_missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest["artifact_version"] != TREND_FINAL_ARTIFACT_VERSION
                or manifest["feature_policy_version"] != TREND_FEATURE_POLICY_VERSION
                or manifest["preprocessing_version"] != TREND_PREPROCESSING_VERSION
                or manifest["outer_2024_accessed"] is not False
                or manifest["2025_accessed"] is not False
                or set(manifest["pollutants_with_models"])
                != APPROVED_TREND_MODEL_POLLUTANTS
                or manifest["unavailable_pollutants"]
                != dict(UNAVAILABLE_TREND_POLLUTANTS)
                or pollutant not in manifest["pollutants_with_models"]
            ):
                raise _Unavailable("trend_inference_failure")
            record = dict(manifest["models"][pollutant])
            record["minimum_history_coverage"] = manifest[
                "minimum_history_coverage"
            ]
            relative = Path(str(record["path"]))
            if relative.name != str(record["path"]) or relative.is_absolute():
                raise _Unavailable("trend_inference_failure")
            artifact_path = self._artifact_directory / relative
            if not artifact_path.is_file():
                raise _Unavailable("trend_artifact_missing")
            model_sha256 = _sha256(artifact_path)
            if model_sha256 != record["sha256"]:
                raise _Unavailable("trend_inference_failure")
            bundle = joblib.load(artifact_path)
            if not isinstance(bundle, FinalSGDModelBundle):
                raise _Unavailable("trend_inference_failure")
            self._validate_bundle(bundle, manifest, record, pollutant)
        except _Unavailable:
            raise
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            raise _Unavailable("trend_inference_failure") from None
        loaded = (bundle, record, model_sha256)
        self._loaded[pollutant] = loaded
        return loaded

    @staticmethod
    def _validate_bundle(
        bundle: FinalSGDModelBundle,
        manifest: Mapping[str, Any],
        record: Mapping[str, Any],
        pollutant: str,
    ) -> None:
        """Reject a model file that does not match what was approved."""
        manifest_vocabulary = record["identity_vocabulary"]
        expected_series = [
            {"station_id": station, "channel_id": channel}
            for station, channel in bundle.identity_vocabulary.series_ids
        ]
        expected_model_version = (
            f"air-pollution-trend-sgd-{pollutant.lower().replace('.', '_')}-"
            "training-2021-2023-v1"
        )
        if (
            bundle.pollutant != pollutant
            or bundle.artifact_version != TREND_FINAL_ARTIFACT_VERSION
            or bundle.model_version != expected_model_version
            or bundle.model_version != record["model_version"]
            or bundle.configuration != record["configuration"]
            or bundle.configuration
            != asdict(LOCKED_TREND_SGD_CONFIGURATIONS[pollutant])
            or bundle.feature_policy_version != TREND_FEATURE_POLICY_VERSION
            or bundle.preprocessing_version != TREND_PREPROCESSING_VERSION
            or bundle.training_start != TREND_FINAL_TRAINING_START
            or bundle.training_end != TREND_FINAL_TRAINING_END
            or [bundle.training_start, bundle.training_end]
            != manifest["training_period"]
            or tuple(bundle.feature_columns) != tuple(FEATURE_COLUMNS)
            or tuple(bundle.labels) != tuple(TREND_LABELS)
            or not np.array_equal(bundle.classifier.classes_, np.arange(3))
            or bundle.epsilon_policy != manifest["epsilon_policy"][pollutant]
            or bundle.identity_vocabulary.version != manifest_vocabulary["version"]
            or list(bundle.identity_vocabulary.station_ids)
            != manifest_vocabulary["station_ids"]
            or list(bundle.identity_vocabulary.channel_ids)
            != manifest_vocabulary["channel_ids"]
            or expected_series != manifest_vocabulary["series_ids"]
            or float(record["minimum_history_coverage"])
            != TREND_MINIMUM_HISTORY_COVERAGE
        ):
            raise _Unavailable("trend_inference_failure")
