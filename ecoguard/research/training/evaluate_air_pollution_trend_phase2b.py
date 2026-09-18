"""Leakage-safe Phase 2B diagnostics, selection, and final candidate fitting.

This research module reuses the Phase 2A feature batches and immutable audit.
Hyperparameter experiments are restricted to 2021-2022 -> 2023.  The guarded
final-fit path uses only the locked configurations and 2021-2023 observations.
No code path may open a 2025 observation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import joblib
import sklearn
from scipy import sparse
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

from ecoguard.paths import GENERATED
from ecoguard.research.datasets.build_air_pollution_trend_dataset import (
    DEFAULT_CACHE,
    SUPPORTED_POLLUTANTS,
    select_series,
)
from ecoguard.research.training.evaluate_air_pollution_trend_phase2a import (
    NAIVE_BASELINE_NAMES,
    ConfusionAccumulator,
    FeatureBatch,
    Phase2AError,
    iter_feature_batches,
    load_series,
    naive_baseline_predictions,
)
from ecoguard.shared.air_pollution_history import AirPollutionSeriesIdentity
from ecoguard.shared.air_pollution_trend_model import (
    FinalSGDModelBundle,
    IdentityVocabulary,
)
from ecoguard.shared.air_pollution_trend_features import (
    FEATURE_COLUMNS,
    LOOKBACK_MINUTES,
    PROVIDER_TIMEZONE,
    TREND_FEATURE_POLICY_VERSION,
)
from ecoguard.shared.air_pollution_trend_policy import (
    LOCKED_TREND_SGD_CONFIGURATIONS,
    TREND_ARTIFACT_FILENAMES,
    TREND_FINAL_ARTIFACT_VERSION,
    TREND_FINAL_TRAINING_END,
    TREND_FINAL_TRAINING_START,
    TREND_FINAL_TRAIN_YEARS,
    TREND_LABELS,
    TREND_LABEL_TO_INT,
    TREND_MINIMUM_HISTORY_COVERAGE,
    TREND_PREPROCESSING_VERSION,
    TREND_RANDOM_SEED,
    UNAVAILABLE_TREND_POLLUTANTS,
    TrendSGDConfiguration,
)

PHASE2B_VERSION = "air-pollution-trend-phase2b-v1"
PREPROCESSING_VERSION = TREND_PREPROCESSING_VERSION
LABELS = TREND_LABELS
LABEL_TO_INT = TREND_LABEL_TO_INT
INNER_TRAIN_YEARS = (2021, 2022)
INNER_VALIDATION_YEARS = (2023,)
INNER_BOUNDARY = datetime(2023, 1, 1, tzinfo=PROVIDER_TIMEZONE)
OUTER_BOUNDARY = datetime(2024, 1, 1, tzinfo=PROVIDER_TIMEZONE)
EMBARGO_MINUTES = 155
MINIMUM_HISTORY_COVERAGE = TREND_MINIMUM_HISTORY_COVERAGE
RANDOM_SEED = TREND_RANDOM_SEED
PARTICULATES = ("PM10", "PM2.5")
DEFAULT_PHASE2A = GENERATED / "ml" / "air_pollution_trend" / "phase2a"
DEFAULT_OUTPUT = GENERATED / "ml" / "air_pollution_trend" / "phase2b"
DEFAULT_FINAL_OUTPUT = GENERATED / "ml" / "air_pollution_trend" / "final"
FINAL_ARTIFACT_VERSION = TREND_FINAL_ARTIFACT_VERSION
FINAL_TRAIN_YEARS = TREND_FINAL_TRAIN_YEARS
FINAL_TRAINING_START = TREND_FINAL_TRAINING_START
FINAL_TRAINING_END = TREND_FINAL_TRAINING_END


class Phase2BError(RuntimeError):
    """A Phase 2B request would violate the research contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_phase2a_artifacts(phase2a_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    audit_path = phase2a_dir / "training_coverage_audit.json"
    result_path = phase2a_dir / "sgd_validation_results.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if audit.get("2025_accessed") is not False or result.get("2025_accessed") is not False:
        raise Phase2BError("Phase 2A artifacts do not prove that 2025 remained sealed")
    if audit.get("stage") != "training_coverage_audit":
        raise Phase2BError("unexpected Phase 2A audit artifact")
    if result.get("stage") != "streaming_linear_baseline_validation":
        raise Phase2BError("unexpected Phase 2A validation artifact")
    return audit, result


def read_training_audit(phase2a_dir: Path) -> dict[str, Any]:
    """Read only the training audit; final fitting must not open 2024 results."""

    path = phase2a_dir / "training_coverage_audit.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    if audit.get("2025_accessed") is not False:
        raise Phase2BError("training audit does not prove that 2025 remained sealed")
    if audit.get("stage") != "training_coverage_audit":
        raise Phase2BError("unexpected Phase 2A audit artifact")
    return audit


def frozen_epsilon(audit: dict[str, Any]) -> dict[str, float]:
    return {
        pollutant: float(audit["pollutants"][pollutant]["stability_band"]["epsilon"])
        for pollutant in SUPPORTED_POLLUTANTS
    }


def inner_allowed_anchor_mask(year: int, count: int) -> np.ndarray:
    """Apply the 155-minute inner and outer embargo without reading 2024."""

    if year not in (2021, 2022, 2023):
        raise Phase2BError("inner model selection is restricted to 2021-2023")
    allowed = np.ones(count, dtype=bool)
    if year == 2021:
        allowed[: LOOKBACK_MINUTES // 5] = False
    if year == 2022:
        allowed[-30:] = False
    if year == 2023:
        allowed[:31] = False
        allowed[-30:] = False
    return allowed


def assert_inner_selection_years(training: Sequence[int], validation: Sequence[int]) -> None:
    if 2025 in training or 2025 in validation:
        raise Phase2BError("2025 observation access is permanently forbidden")
    if tuple(training) != INNER_TRAIN_YEARS or tuple(validation) != INNER_VALIDATION_YEARS:
        raise Phase2BError("hyperparameters require 2021-2022 -> 2023 exactly")


def transform_sgd_features(
    scaler: StandardScaler,
    vocabulary: IdentityVocabulary,
    batch: FeatureBatch,
) -> sparse.csr_matrix:
    numeric = scaler.transform(batch.x)
    numeric = np.nan_to_num(numeric, nan=0.0, posinf=0.0, neginf=0.0)
    return sparse.hstack(
        (sparse.csr_matrix(numeric), vocabulary.sparse_one_hot(batch.identity, len(numeric))),
        format="csr",
    )


def transform_histgb_features(
    vocabulary: IdentityVocabulary,
    batch: FeatureBatch,
    row_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Build dense float32 HistGB input with explicitly categorical identity."""

    numeric = batch.x if row_mask is None else batch.x[row_mask]
    identity = vocabulary.categorical_codes(batch.identity, len(numeric))
    return np.column_stack((numeric, identity)).astype(np.float32, copy=False)


SGDCandidate = TrendSGDConfiguration


SGD_CANDIDATES = (
    SGDCandidate("phase2a_balanced_optimal_1epoch", True, 1, "optimal", False),
    SGDCandidate("phase2a_unweighted_optimal_1epoch", False, 1, "optimal", False),
    SGDCandidate("phase2b_balanced_optimal_1epoch", True, 1, "optimal"),
    SGDCandidate("phase2b_unweighted_optimal_1epoch", False, 1, "optimal"),
    SGDCandidate("phase2b_balanced_optimal_3epoch", True, 3, "optimal"),
    SGDCandidate("phase2b_unweighted_optimal_3epoch", False, 3, "optimal"),
    SGDCandidate(
        "phase2b_unweighted_constant_3epoch", False, 3, "constant", eta0=0.001
    ),
    SGDCandidate(
        "phase2b_unweighted_invscaling_3epoch",
        False,
        3,
        "invscaling",
        eta0=0.01,
        power_t=0.25,
    ),
)

LOCKED_FINAL_CANDIDATES = LOCKED_TREND_SGD_CONFIGURATIONS


def final_training_allowed_anchor_mask(year: int, count: int) -> np.ndarray:
    """Keep every feature/target inside sealed 2021-2023 training time."""

    if year not in FINAL_TRAIN_YEARS:
        raise Phase2BError("final fitting is restricted to 2021-2023")
    allowed = np.ones(count, dtype=bool)
    if year == 2021:
        allowed[: LOOKBACK_MINUTES // 5] = False
    if year == 2023:
        allowed[-30:] = False
    return allowed


def _identity_vocabulary_manifest(
    vocabulary: IdentityVocabulary,
) -> dict[str, Any]:
    return {
        "version": vocabulary.version,
        "fit_scope": "final training 2021-2023 only",
        "non_ordinal": True,
        "unseen_behavior": "dedicated UNKNOWN one-hot feature",
        "station_ids": list(vocabulary.station_ids),
        "channel_ids": list(vocabulary.channel_ids),
        "series_ids": [
            {"station_id": station, "channel_id": channel}
            for station, channel in vocabulary.series_ids
        ],
    }


class SeriesMetrics:
    """Retain equal-weight series metrics alongside row-weighted totals."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = tuple(names)
        self.overall = {name: ConfusionAccumulator() for name in self.names}
        self.by_series: dict[
            AirPollutionSeriesIdentity, dict[str, ConfusionAccumulator]
        ] = {}

    def add(
        self,
        identity: AirPollutionSeriesIdentity,
        truth: np.ndarray,
        predictions: dict[str, np.ndarray],
    ) -> None:
        series = self.by_series.setdefault(
            identity, {name: ConfusionAccumulator() for name in self.names}
        )
        for name in self.names:
            self.overall[name].add(truth, predictions[name])
            series[name].add(truth, predictions[name])

    def report(self) -> dict[str, Any]:
        aggregate = {name: item.metrics() for name, item in self.overall.items()}
        macro_across_series: dict[str, Any] = {}
        for name in self.names:
            values = [items[name].metrics() for items in self.by_series.values()]
            macro_across_series[name] = {
                "series_count": len(values),
                "mean_series_macro_f1": float(np.mean([item["macro_f1"] for item in values])),
                "mean_series_balanced_accuracy": float(
                    np.mean([item["balanced_accuracy"] for item in values])
                ),
            }
        return {
            "row_weighted": aggregate,
            "equal_weight_series_macro": macro_across_series,
        }


def _class_weights(counts: np.ndarray) -> np.ndarray:
    if np.any(counts == 0):
        raise Phase2BError("all three classes must exist in inner training")
    return counts.sum() / (3.0 * counts)


def _selected_series(
    cache_dir: Path,
    pollutants: Sequence[str],
    max_series_per_pollutant: int | None,
) -> list[tuple[AirPollutionSeriesIdentity, list[Path]]]:
    selected: list[tuple[AirPollutionSeriesIdentity, list[Path]]] = []
    for pollutant in pollutants:
        rows, _ = select_series(
            cache_dir,
            pollutant=pollutant,
            max_series=max_series_per_pollutant,
        )
        selected.extend(rows)
    return sorted(selected, key=lambda item: item[0])


def _batch_stream(
    cache_dir: Path,
    years: tuple[int, ...],
    epsilon: dict[str, float],
    selected: Sequence[tuple[AirPollutionSeriesIdentity, list[Path]]],
) -> Iterable[FeatureBatch]:
    return iter_feature_batches(
        cache_dir,
        years,
        epsilon,
        MINIMUM_HISTORY_COVERAGE,
        selected_series=selected,
        allowed_anchor_mask=inner_allowed_anchor_mask,
    )


def _read_locked_selection(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("phase2b_version") != PHASE2B_VERSION:
        raise Phase2BError("unexpected Phase 2B selection artifact")
    if result.get("outer_2024_used_for_selection") is not False:
        raise Phase2BError("locked selection must not use outer 2024")
    if result.get("2025_accessed") is not False:
        raise Phase2BError("locked selection does not prove that 2025 remained sealed")
    if result.get("development_limit", {}).get("active") is not False:
        raise Phase2BError("locked selection must be the complete national experiment")
    if result.get("inner_training") != [
        "2021-01-01T00:00:00+02:00",
        INNER_BOUNDARY.isoformat(),
    ] or result.get("inner_validation") != [
        INNER_BOUNDARY.isoformat(),
        OUTER_BOUNDARY.isoformat(),
    ]:
        raise Phase2BError("locked selection does not use 2021-2022 -> 2023")
    available = {
        item.get("name"): item
        for item in result.get("candidate_configuration", [])
        if isinstance(item, dict)
    }
    for candidate in LOCKED_FINAL_CANDIDATES.values():
        if available.get(candidate.name) != asdict(candidate):
            raise Phase2BError(f"locked configuration missing: {candidate.name}")
    return result


def _locked_final_series(
    cache_dir: Path,
    selection: dict[str, Any],
) -> list[tuple[AirPollutionSeriesIdentity, list[Path]]]:
    """Resolve exact 2021-2023 paths without enumerating 2024/2025 files."""

    accepted = frozenset(LOCKED_FINAL_CANDIDATES)
    identities = []
    for item in selection.get("selected_identities", []):
        identity = AirPollutionSeriesIdentity(
            station_id=str(item["station_id"]),
            channel_id=str(item["channel_id"]),
            pollutant=str(item["pollutant"]),
        )
        if identity.pollutant in accepted:
            identities.append(identity)
    identities = sorted(set(identities))
    if not identities or {item.pollutant for item in identities} != accepted:
        raise Phase2BError("selection artifact lacks accepted pollutant identities")
    actual_counts = Counter(item.pollutant for item in identities)
    expected_counts = selection.get("selected_series", {})
    if any(
        actual_counts[pollutant] != expected_counts.get(pollutant)
        for pollutant in accepted
    ):
        raise Phase2BError("selection identity counts do not match national report")

    selected = []
    for identity in identities:
        slug = identity.pollutant.lower().replace(".", "_")
        directory = (
            cache_dir
            / f"station_{identity.station_id}"
            / f"channel_{identity.channel_id}_{slug}"
        )
        files = [
            directory / f"{year}-{month:02d}.json.gz"
            for year in FINAL_TRAIN_YEARS
            for month in range(1, 13)
            if (directory / f"{year}-{month:02d}.json.gz").is_file()
        ]
        if not files:
            raise Phase2BError(
                f"no 2021-2023 cache files for {identity.station_id}:"
                f"{identity.channel_id}:{identity.pollutant}"
            )
        selected.append((identity, files))
    return selected


def _final_batch_stream(
    cache_dir: Path,
    epsilon: dict[str, float],
    selected: Sequence[tuple[AirPollutionSeriesIdentity, list[Path]]],
) -> Iterable[FeatureBatch]:
    return iter_feature_batches(
        cache_dir,
        FINAL_TRAIN_YEARS,
        epsilon,
        MINIMUM_HISTORY_COVERAGE,
        selected_series=selected,
        allowed_anchor_mask=final_training_allowed_anchor_mask,
    )


def run_final_sgd_fit(
    cache_dir: Path,
    audit: dict[str, Any],
    selection: dict[str, Any],
    output_dir: Path,
    *,
    audit_path: Path,
    selection_path: Path,
) -> dict[str, Any]:
    """Fit and serialize only the four locked models on sealed 2021-2023 data."""

    if "PM10" in LOCKED_FINAL_CANDIDATES:
        raise Phase2BError("PM10 must not receive a final SGD artifact")
    epsilon = frozen_epsilon(audit)
    selected = _locked_final_series(cache_dir, selection)
    pollutants = tuple(LOCKED_FINAL_CANDIDATES)
    scalers = {pollutant: StandardScaler() for pollutant in pollutants}
    counts = {pollutant: np.zeros(3, dtype=np.int64) for pollutant in pollutants}
    seen = {pollutant: set() for pollutant in pollutants}
    smoke_inputs: dict[str, tuple[AirPollutionSeriesIdentity, np.ndarray]] = {}
    started = time.perf_counter()

    expected_outputs = [
        output_dir / TREND_ARTIFACT_FILENAMES[pollutant]
        for pollutant in pollutants
    ] + [output_dir / "manifest.json"]
    existing = [str(path) for path in expected_outputs if path.exists()]
    if existing:
        raise Phase2BError(f"refusing to overwrite final artifacts: {existing}")

    for batch in _final_batch_stream(cache_dir, epsilon, selected):
        pollutant = batch.identity.pollutant
        scalers[pollutant].partial_fit(batch.x)
        counts[pollutant] += np.bincount(batch.y, minlength=3)
        seen[pollutant].add(batch.identity)
        smoke_inputs.setdefault(pollutant, (batch.identity, batch.x[:1].copy()))

    vocabularies = {
        pollutant: IdentityVocabulary.fit(seen[pollutant]) for pollutant in pollutants
    }
    models = {
        pollutant: LOCKED_FINAL_CANDIDATES[pollutant].classifier()
        for pollutant in pollutants
    }
    initialized: set[str] = set()
    for _epoch in range(1, 4):
        for batch in _final_batch_stream(cache_dir, epsilon, selected):
            pollutant = batch.identity.pollutant
            candidate = LOCKED_FINAL_CANDIDATES[pollutant]
            weights = _class_weights(counts[pollutant])
            kwargs = {"classes": np.arange(3)} if pollutant not in initialized else {}
            models[pollutant].partial_fit(
                transform_sgd_features(
                    scalers[pollutant], vocabularies[pollutant], batch
                ),
                batch.y,
                sample_weight=weights[batch.y] if candidate.weighted else None,
                **kwargs,
            )
            initialized.add(pollutant)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_records: dict[str, Any] = {}
    for pollutant in pollutants:
        stability_band = dict(audit["pollutants"][pollutant]["stability_band"])
        if (
            stability_band.get("training_start") != FINAL_TRAINING_START
            or stability_band.get("training_end") != FINAL_TRAINING_END
        ):
            raise Phase2BError("epsilon policy is not fitted on 2021-2023 exactly")
        candidate = LOCKED_FINAL_CANDIDATES[pollutant]
        model_version = (
            f"air-pollution-trend-sgd-{pollutant.lower().replace('.', '_')}-"
            "training-2021-2023-v1"
        )
        bundle = FinalSGDModelBundle(
            artifact_version=FINAL_ARTIFACT_VERSION,
            model_version=model_version,
            pollutant=pollutant,
            training_start=FINAL_TRAINING_START,
            training_end=FINAL_TRAINING_END,
            feature_policy_version=TREND_FEATURE_POLICY_VERSION,
            preprocessing_version=PREPROCESSING_VERSION,
            epsilon_policy=stability_band,
            configuration=asdict(candidate),
            feature_columns=tuple(FEATURE_COLUMNS),
            labels=tuple(LABELS),
            scaler=scalers[pollutant],
            identity_vocabulary=vocabularies[pollutant],
            classifier=models[pollutant],
        )
        artifact_path = output_dir / TREND_ARTIFACT_FILENAMES[pollutant]
        joblib.dump(bundle, artifact_path)
        loaded = joblib.load(artifact_path)
        if not isinstance(loaded, FinalSGDModelBundle):
            raise Phase2BError("joblib smoke test loaded an unexpected bundle type")
        smoke_identity, smoke_values = smoke_inputs[pollutant]
        expected = bundle.predict_proba(smoke_values, smoke_identity)
        actual = loaded.predict_proba(smoke_values, smoke_identity)
        if (
            expected.shape != (1, 3)
            or not np.isfinite(actual).all()
            or not np.allclose(expected, actual)
            or not np.allclose(actual.sum(axis=1), 1.0)
        ):
            raise Phase2BError("joblib load/predict smoke test failed")
        artifact_records[pollutant] = {
            "path": artifact_path.name,
            "sha256": _sha256(artifact_path),
            "model_version": model_version,
            "configuration": asdict(candidate),
            "training_class_counts": {
                label: int(counts[pollutant][index])
                for index, label in enumerate(LABELS)
            },
            "identity_vocabulary": _identity_vocabulary_manifest(
                vocabularies[pollutant]
            ),
            "load_predict_smoke_test": "passed",
        }

    feature_schema_sha256 = hashlib.sha256(
        json.dumps(list(FEATURE_COLUMNS), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = {
        "artifact_version": FINAL_ARTIFACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "training_period": [FINAL_TRAINING_START, FINAL_TRAINING_END],
        "training_years": list(FINAL_TRAIN_YEARS),
        "feature_policy_version": TREND_FEATURE_POLICY_VERSION,
        "feature_schema_sha256": feature_schema_sha256,
        "preprocessing_version": PREPROCESSING_VERSION,
        "minimum_history_coverage": MINIMUM_HISTORY_COVERAGE,
        "embargo_minutes": EMBARGO_MINUTES,
        "pollutants_with_models": list(pollutants),
        "unavailable_pollutants": dict(UNAVAILABLE_TREND_POLLUTANTS),
        "models": artifact_records,
        "epsilon_policy": {
            pollutant: audit["pollutants"][pollutant]["stability_band"]
            for pollutant in pollutants
        },
        "source_checksums": {
            "training_coverage_audit_sha256": _sha256(audit_path),
            "phase2b_inner_selection_sha256": _sha256(selection_path),
        },
        "software": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "runtime_seconds": time.perf_counter() - started,
        "outer_2024_accessed": False,
        "2025_accessed": False,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def run_inner_sgd_experiment(
    cache_dir: Path,
    audit: dict[str, Any],
    *,
    pollutants: Sequence[str],
    max_series_per_pollutant: int | None,
    candidates: Sequence[SGDCandidate] = SGD_CANDIDATES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fit controlled candidates on 2021-2022 and evaluate only on 2023."""

    assert_inner_selection_years(INNER_TRAIN_YEARS, INNER_VALIDATION_YEARS)
    epsilon = frozen_epsilon(audit)
    selected = _selected_series(cache_dir, pollutants, max_series_per_pollutant)
    scalers = {pollutant: StandardScaler() for pollutant in pollutants}
    counts = {pollutant: np.zeros(3, dtype=np.int64) for pollutant in pollutants}
    seen = {pollutant: set() for pollutant in pollutants}
    started = time.perf_counter()

    for batch in _batch_stream(cache_dir, INNER_TRAIN_YEARS, epsilon, selected):
        pollutant = batch.identity.pollutant
        scalers[pollutant].partial_fit(batch.x)
        counts[pollutant] += np.bincount(batch.y, minlength=3)
        seen[pollutant].add(batch.identity)

    vocabularies = {
        pollutant: IdentityVocabulary.fit(seen[pollutant]) for pollutant in pollutants
    }
    models = {
        pollutant: {candidate.name: candidate.classifier() for candidate in candidates}
        for pollutant in pollutants
    }
    initialized: set[tuple[str, str]] = set()
    maximum_epochs = max(candidate.epochs for candidate in candidates)
    for epoch in range(1, maximum_epochs + 1):
        for batch in _batch_stream(cache_dir, INNER_TRAIN_YEARS, epsilon, selected):
            pollutant = batch.identity.pollutant
            numeric = scalers[pollutant].transform(batch.x)
            numeric = sparse.csr_matrix(np.nan_to_num(
                numeric, nan=0.0, posinf=0.0, neginf=0.0
            ))
            with_identity = transform_sgd_features(
                scalers[pollutant], vocabularies[pollutant], batch
            )
            weights = _class_weights(counts[pollutant])
            for candidate in candidates:
                if candidate.epochs < epoch:
                    continue
                key = (pollutant, candidate.name)
                sample_weight = weights[batch.y] if candidate.weighted else None
                kwargs = {"classes": np.arange(3)} if key not in initialized else {}
                models[pollutant][candidate.name].partial_fit(
                    with_identity if candidate.include_identity else numeric,
                    batch.y,
                    sample_weight=sample_weight,
                    **kwargs,
                )
                initialized.add(key)

    names = (*NAIVE_BASELINE_NAMES, *(candidate.name for candidate in candidates))
    metrics = {pollutant: SeriesMetrics(names) for pollutant in pollutants}
    fallback = {pollutant: Counter() for pollutant in pollutants}
    majority = {pollutant: int(np.argmax(counts[pollutant])) for pollutant in pollutants}
    for batch in _batch_stream(cache_dir, INNER_VALIDATION_YEARS, epsilon, selected):
        pollutant = batch.identity.pollutant
        predictions, missing = naive_baseline_predictions(
            batch.x,
            majority_class=majority[pollutant],
            epsilon=epsilon[pollutant],
        )
        fallback[pollutant].update(missing)
        numeric = scalers[pollutant].transform(batch.x)
        numeric = sparse.csr_matrix(np.nan_to_num(
            numeric, nan=0.0, posinf=0.0, neginf=0.0
        ))
        with_identity = transform_sgd_features(
            scalers[pollutant], vocabularies[pollutant], batch
        )
        for candidate in candidates:
            predictions[candidate.name] = models[pollutant][candidate.name].predict(
                with_identity if candidate.include_identity else numeric
            )
        metrics[pollutant].add(batch.identity, batch.y, predictions)

    report = {
        "phase2b_version": PHASE2B_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
        "inner_training": ["2021-01-01T00:00:00+02:00", INNER_BOUNDARY.isoformat()],
        "inner_validation": [INNER_BOUNDARY.isoformat(), OUTER_BOUNDARY.isoformat()],
        "embargo_minutes": EMBARGO_MINUTES,
        "outer_2024_used_for_selection": False,
        "2025_accessed": False,
        "development_limit": {
            "active": max_series_per_pollutant is not None,
            "max_series_per_pollutant": max_series_per_pollutant,
        },
        "selected_series": {
            pollutant: sum(item[0].pollutant == pollutant for item in selected)
            for pollutant in pollutants
        },
        "selected_identities": [
            {
                "station_id": identity.station_id,
                "channel_id": identity.channel_id,
                "pollutant": identity.pollutant,
            }
            for identity, _files in selected
        ],
        "candidate_configuration": [asdict(candidate) for candidate in candidates],
        "training_class_counts": {
            pollutant: {
                label: int(counts[pollutant][index]) for index, label in enumerate(LABELS)
            }
            for pollutant in pollutants
        },
        "identity_vocabulary": {
            pollutant: vocabularies[pollutant].to_dict() for pollutant in pollutants
        },
        "inner_validation_metrics": {
            pollutant: metrics[pollutant].report() for pollutant in pollutants
        },
        "missing_naive_feature_fallback_counts": {
            pollutant: dict(fallback[pollutant]) for pollutant in pollutants
        },
        "runtime_seconds": time.perf_counter() - started,
    }
    context = {
        "scalers": scalers,
        "models": models,
        "vocabularies": vocabularies,
        "selected": selected,
    }
    return report, context


def _quantization_report(
    cache_dir: Path,
    selected: Sequence[tuple[AirPollutionSeriesIdentity, list[Path]]],
    epsilon: dict[str, float],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for pollutant in PARTICULATES:
        differences: list[float] = []
        value_count = 0
        one_decimal_count = 0
        pollutant_series = [item for item in selected if item[0].pollutant == pollutant]
        for identity, files in pollutant_series:
            observations = load_series(identity, files, set(INNER_TRAIN_YEARS))
            value_count += len(observations)
            one_decimal_count += sum(
                abs(item.value * 10 - round(item.value * 10)) < 1e-8
                for item in observations
            )
            differences.extend(
                right.value - left.value
                for left, right in zip(observations, observations[1:])
                if right.observed_at - left.observed_at == timedelta(minutes=5)
            )
        rounded = [round(abs(value), 6) for value in differences]
        nonzero = [value for value in rounded if value > 0]
        common = Counter(nonzero).most_common(8)
        output[pollutant] = {
            "scope": "selected development series, inner training 2021-2022 only",
            "series_count": len(pollutant_series),
            "value_count": value_count,
            "share_values_on_0_1_grid": one_decimal_count / value_count if value_count else None,
            "exact_adjacent_difference_count": len(differences),
            "zero_adjacent_difference_share": (
                sum(value == 0 for value in rounded) / len(rounded) if rounded else None
            ),
            "minimum_nonzero_absolute_difference": min(nonzero, default=None),
            "most_common_nonzero_absolute_differences": [
                {"difference": value, "count": count} for value, count in common
            ],
            "frozen_epsilon": epsilon[pollutant],
            "share_absolute_differences_within_epsilon": (
                sum(value <= epsilon[pollutant] for value in rounded) / len(rounded)
                if rounded else None
            ),
        }
    return output


def _coefficient_report(
    context: dict[str, Any], candidates: Sequence[SGDCandidate]
) -> dict[str, Any]:
    change_index = FEATURE_COLUMNS.index("change_from_lag_5m")
    output: dict[str, Any] = {}
    for pollutant in PARTICULATES:
        scaler = context["scalers"][pollutant]
        vocabulary = context["vocabularies"][pollutant]
        names = (*FEATURE_COLUMNS, *vocabulary.feature_names)
        candidates_report: dict[str, Any] = {}
        for candidate in candidates:
            coefficients = context["models"][pollutant][candidate.name].coef_
            candidate_names = names if candidate.include_identity else FEATURE_COLUMNS
            per_class = {}
            for class_index, label in enumerate(LABELS):
                absolute = np.abs(coefficients[class_index])
                rank = int(np.flatnonzero(np.argsort(-absolute) == change_index)[0]) + 1
                top = np.argsort(-absolute)[:10]
                per_class[label] = {
                    "change_from_lag_5m_standardized_coefficient": float(
                        coefficients[class_index, change_index]
                    ),
                    "absolute_rank_among_all_features": rank,
                    "top_absolute_coefficients": [
                        {
                            "feature": candidate_names[index],
                            "coefficient": float(coefficients[class_index, index]),
                        }
                        for index in top
                    ],
                }
            candidates_report[candidate.name] = per_class
        output[pollutant] = {
            "raw_training_mean": float(scaler.mean_[change_index]),
            "raw_training_scale": float(scaler.scale_[change_index]),
            "standardized_before_sgd": True,
            "candidate_coefficients": candidates_report,
        }
    return output


@dataclass(frozen=True)
class HistGBMonthlyBlockPolicy:
    """One rotating complete local day per month, applied to every series."""

    seed: int = RANDOM_SEED
    block_hours: int = 24
    days_per_month: int = 1
    version: str = "all-series-rotating-monthly-day-v1"

    def day(self, year: int, month: int) -> int:
        if year not in (2021, 2022, 2023) or not 1 <= month <= 12:
            raise Phase2BError("HistGB subset planning is restricted to 2021-2023")
        return 1 + ((self.seed + (year - 2021) * 9 + (month - 1) * 7) % 27)

    def block_dates(self, years: Sequence[int]) -> list[str]:
        return [
            f"{year:04d}-{month:02d}-{self.day(year, month):02d}"
            for year in years
            for month in range(1, 13)
        ]

    def includes(self, moment: datetime) -> bool:
        local = moment.astimezone(PROVIDER_TIMEZONE)
        return local.year in (2021, 2022, 2023) and local.day == self.day(
            local.year, local.month
        )


def histgb_classifier(numeric_features: int = len(FEATURE_COLUMNS)) -> HistGradientBoostingClassifier:
    categorical = np.zeros(numeric_features + 3, dtype=bool)
    categorical[-3:] = True
    return HistGradientBoostingClassifier(
        loss="log_loss",
        learning_rate=0.05,
        max_iter=200,
        max_leaf_nodes=31,
        min_samples_leaf=40,
        l2_regularization=1.0,
        categorical_features=categorical,
        random_state=RANDOM_SEED,
    )


def experiment_plan(
    audit: dict[str, Any],
    phase2a_result: dict[str, Any],
    *,
    phase2a_dir: Path = DEFAULT_PHASE2A,
) -> dict[str, Any]:
    measured_seconds = float(phase2a_result["runtime_seconds"])
    seconds_per_year_pass = measured_seconds / 7.0
    policy = HistGBMonthlyBlockPolicy()
    retained = {
        pollutant: int(phase2a_result["training"][pollutant]["included_examples"])
        for pollutant in SUPPORTED_POLLUTANTS
    }
    hist_rows = {
        pollutant: {
            "before_selection_exact": retained[pollutant],
            "inner_train_estimate_2021_2022": round(retained[pollutant] * 24 / 1095),
            "final_train_estimate_2021_2023": round(retained[pollutant] * 36 / 1095),
            "exact_after_selection": None,
        }
        for pollutant in SUPPORTED_POLLUTANTS
    }
    for pollutant, item in hist_rows.items():
        rows = item["final_train_estimate_2021_2023"]
        item["float32_numeric_plus_3_category_megabytes"] = round(
            rows * (len(FEATURE_COLUMNS) + 3) * 4 / 1024 ** 2, 1
        )
        item["working_memory_estimate_megabytes"] = round(
            item["float32_numeric_plus_3_category_megabytes"] * 3.0, 1
        )
        counts = phase2a_result["training"][pollutant]["class_counts"]
        total = sum(counts.values())
        item["class_prevalence_before_selection"] = {
            label: counts[label] / total for label in LABELS
        }
        item["class_prevalence_after_selection"] = None
    return {
        "phase2b_version": PHASE2B_VERSION,
        "2025_accessed": False,
        "sgd_national_inner_experiment": {
            "candidate_matrix": [asdict(candidate) for candidate in SGD_CANDIDATES],
            "archive_passes": {
                "inner_training_preprocessing_2021_2022": 1,
                "shared_inner_training_epochs_2021_2022": 3,
                "inner_validation_2023": 1,
                "equivalent_year_passes": 9,
            },
            "estimated_runtime_seconds": round(seconds_per_year_pass * 9),
            "command": (
                r".\.ml-venv\Scripts\python.exe -m "
                "ecoguard.research.training.evaluate_air_pollution_trend_phase2b "
                "sgd-inner --confirm-long-national-run"
            ),
            "approval_required_before_run": True,
        },
        "hist_gradient_boosting": {
            "policy": asdict(policy),
            "all_series_included": True,
            "silent_sampling": False,
            "selection_rule": "all eligible anchors on one rotating complete local day per month",
            "inner_training_blocks": policy.block_dates(INNER_TRAIN_YEARS),
            "inner_validation": "full streaming 2023 preferred; selected-day smoke allowed",
            "final_training_blocks_after_selection": policy.block_dates((2021, 2022, 2023)),
            "rows_and_memory": hist_rows,
            "exact_counts_and_after_prevalence_status": (
                "pending one full training-only planning pass; not run because estimate exceeds 30 minutes"
            ),
            "planning_pass_estimated_runtime_seconds": round(seconds_per_year_pass * 3),
            "exact_planning_command": (
                r".\.ml-venv\Scripts\python.exe -m "
                "ecoguard.research.training.evaluate_air_pollution_trend_phase2b "
                "histgb-plan-exact --confirm-long-national-run"
            ),
            "fit_runtime_estimate": "20-60 minutes per pollutant after extraction; benchmark required",
            "representativeness": (
                "every series, year, month, season and rotating weekday is retained; contiguous daily "
                "blocks preserve temporal structure and avoid row-random sampling"
            ),
            "model_configuration": {
                "family": "HistGradientBoostingClassifier",
                "loss": "log_loss",
                "learning_rate": 0.05,
                "max_iter": 200,
                "max_leaf_nodes": 31,
                "min_samples_leaf": 40,
                "l2_regularization": 1.0,
                "identity": "three training-vocabulary categorical columns",
            },
        },
        "artifact_sources": {
            "audit_sha256": _sha256(phase2a_dir / "training_coverage_audit.json"),
            "phase2a_result_sha256": _sha256(
                phase2a_dir / "sgd_validation_results.json"
            ),
        },
    }


def run_exact_histgb_subset_plan(
    cache_dir: Path,
    audit: dict[str, Any],
    *,
    max_series_per_pollutant: int | None = None,
) -> dict[str, Any]:
    """Count the deterministic HistGB subset without retaining feature batches."""

    policy = HistGBMonthlyBlockPolicy()
    epsilon = frozen_epsilon(audit)
    selected = _selected_series(
        cache_dir, SUPPORTED_POLLUTANTS, max_series_per_pollutant
    )
    before = {pollutant: np.zeros(3, dtype=np.int64) for pollutant in SUPPORTED_POLLUTANTS}
    after = {pollutant: np.zeros(3, dtype=np.int64) for pollutant in SUPPORTED_POLLUTANTS}
    covered = {pollutant: set() for pollutant in SUPPORTED_POLLUTANTS}
    started = time.perf_counter()
    for batch in _batch_stream(cache_dir, (2021, 2022, 2023), epsilon, selected):
        pollutant = batch.identity.pollutant
        before[pollutant] += np.bincount(batch.y, minlength=3)
        central_slots = np.flatnonzero(batch.mask)
        selected_days = np.asarray([
            datetime(
                batch.arrays.year,
                month,
                policy.day(batch.arrays.year, month),
            ).timetuple().tm_yday - 1
            for month in range(1, 13)
        ])
        selected_rows = np.isin(central_slots // 288, selected_days)
        if selected_rows.any():
            after[pollutant] += np.bincount(batch.y[selected_rows], minlength=3)
            covered[pollutant].add(batch.identity)
    return {
        "phase2b_version": PHASE2B_VERSION,
        "stage": "exact_histgb_subset_plan",
        "2024_accessed": False,
        "2025_accessed": False,
        "policy": asdict(policy),
        "development_limit": {
            "active": max_series_per_pollutant is not None,
            "max_series_per_pollutant": max_series_per_pollutant,
        },
        "pollutants": {
            pollutant: {
                "class_counts_before_selection": {
                    label: int(before[pollutant][index])
                    for index, label in enumerate(LABELS)
                },
                "class_counts_after_selection": {
                    label: int(after[pollutant][index])
                    for index, label in enumerate(LABELS)
                },
                "class_prevalence_before_selection": {
                    label: float(before[pollutant][index] / before[pollutant].sum())
                    for index, label in enumerate(LABELS)
                },
                "class_prevalence_after_selection": {
                    label: float(after[pollutant][index] / after[pollutant].sum())
                    for index, label in enumerate(LABELS)
                },
                "selected_rows": int(after[pollutant].sum()),
                "covered_series": len(covered[pollutant]),
                "covered_stations": len({
                    identity.station_id for identity in covered[pollutant]
                }),
            }
            for pollutant in SUPPORTED_POLLUTANTS
        },
        "runtime_seconds": time.perf_counter() - started,
    }


def run_particulate_diagnostics(
    cache_dir: Path,
    phase2a_dir: Path,
    output_path: Path,
    *,
    max_series_per_pollutant: int,
) -> dict[str, Any]:
    if max_series_per_pollutant < 1:
        raise Phase2BError("development series limit must be positive")
    audit, phase2a = read_phase2a_artifacts(phase2a_dir)
    candidates = SGD_CANDIDATES
    report, context = run_inner_sgd_experiment(
        cache_dir,
        audit,
        pollutants=PARTICULATES,
        max_series_per_pollutant=max_series_per_pollutant,
        candidates=candidates,
    )
    epsilon = frozen_epsilon(audit)
    diagnostic = {
        "phase2b_version": PHASE2B_VERSION,
        "stage": "particulate_development_diagnostics",
        "2024_accessed": False,
        "2025_accessed": False,
        "scope_warning": "development series limit; do not generalize sample metrics nationally",
        "phase2a_identity_finding": {
            "ordinal_numeric": False,
            "included_in_model_matrix": False,
            "finding": "Phase 2A preserved identity as metadata but omitted it from SGD features",
        },
        "frozen_epsilon_unchanged": {
            pollutant: audit["pollutants"][pollutant]["stability_band"]
            for pollutant in PARTICULATES
        },
        "phase2a_outer_validation_evidence": {
            pollutant: phase2a["validation_metrics"][pollutant]
            for pollutant in PARTICULATES
        },
        "inner_experiment": report,
        "quantization": _quantization_report(
            cache_dir, context["selected"], epsilon
        ),
        "scaling_and_coefficients": _coefficient_report(context, candidates),
        "source_artifacts": {
            "audit_sha256": _sha256(phase2a_dir / "training_coverage_audit.json"),
            "phase2a_result_sha256": _sha256(
                phase2a_dir / "sgd_validation_results.json"
            ),
        },
        "python_environment": {
            "numpy": np.__version__,
            "sklearn": sklearn.__version__,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return diagnostic


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "plan",
            "diagnose-particulates",
            "sgd-inner",
            "sgd-final-fit",
            "histgb-plan-exact",
        ),
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--phase2a-dir", type=Path, default=DEFAULT_PHASE2A)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--final-output-dir", type=Path, default=DEFAULT_FINAL_OUTPUT)
    parser.add_argument("--pollutant", choices=SUPPORTED_POLLUTANTS, action="append")
    parser.add_argument("--max-series-per-pollutant", type=int)
    parser.add_argument("--confirm-long-national-run", action="store_true")
    args = parser.parse_args(argv)
    if args.stage == "sgd-final-fit":
        if not args.confirm_long_national_run:
            raise SystemExit(
                "national final SGD fitting is estimated above 30 minutes; pass "
                "--confirm-long-national-run only after explicit approval"
            )
        if args.pollutant or args.max_series_per_pollutant is not None:
            raise SystemExit(
                "final fitting uses exactly the four locked national configurations; "
                "pollutant and development-series filters are forbidden"
            )
        audit_path = args.phase2a_dir / "training_coverage_audit.json"
        selection_path = args.output_dir / "sgd_inner_results.json"
        audit = read_training_audit(args.phase2a_dir)
        selection = _read_locked_selection(selection_path)
        result = run_final_sgd_fit(
            args.cache_dir,
            audit,
            selection,
            args.final_output_dir,
            audit_path=audit_path,
            selection_path=selection_path,
        )
        path = args.final_output_dir / "manifest.json"
        print(json.dumps({
            "stage": args.stage,
            "output": str(path),
            "2025_accessed": result["2025_accessed"],
        }, sort_keys=True))
        return 0

    audit, phase2a = read_phase2a_artifacts(args.phase2a_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.stage == "plan":
        result = experiment_plan(audit, phase2a, phase2a_dir=args.phase2a_dir)
        path = args.output_dir / "experiment_plan.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif args.stage == "diagnose-particulates":
        limit = args.max_series_per_pollutant or 2
        path = args.output_dir / "particulate_diagnostics.json"
        result = run_particulate_diagnostics(
            args.cache_dir,
            args.phase2a_dir,
            path,
            max_series_per_pollutant=limit,
        )
    elif args.stage == "sgd-inner":
        if args.max_series_per_pollutant is None and not args.confirm_long_national_run:
            raise SystemExit(
                "national inner SGD is estimated above 30 minutes; pass "
                "--confirm-long-national-run only after explicit approval"
            )
        pollutants = tuple(args.pollutant or SUPPORTED_POLLUTANTS)
        result, _ = run_inner_sgd_experiment(
            args.cache_dir,
            audit,
            pollutants=pollutants,
            max_series_per_pollutant=args.max_series_per_pollutant,
        )
        path = args.output_dir / "sgd_inner_results.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        if args.max_series_per_pollutant is None and not args.confirm_long_national_run:
            raise SystemExit(
                "national HistGB subset planning is estimated above 30 minutes; pass "
                "--confirm-long-national-run only after explicit approval"
            )
        result = run_exact_histgb_subset_plan(
            args.cache_dir,
            audit,
            max_series_per_pollutant=args.max_series_per_pollutant,
        )
        path = args.output_dir / "histgb_subset_exact_plan.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "stage": args.stage,
        "output": str(path),
        "2025_accessed": result["2025_accessed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
