from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pytest
from sklearn.preprocessing import StandardScaler

from ecoguard.research.training.evaluate_air_pollution_trend_phase2a import (
    Phase2AError,
    load_series,
)
from ecoguard.research.training.evaluate_air_pollution_trend_phase2b import (
    INNER_TRAIN_YEARS,
    INNER_VALIDATION_YEARS,
    FINAL_ARTIFACT_VERSION,
    FINAL_TRAIN_YEARS,
    LOCKED_FINAL_CANDIDATES,
    PREPROCESSING_VERSION,
    SGD_CANDIDATES,
    FinalSGDModelBundle,
    HistGBMonthlyBlockPolicy,
    IdentityVocabulary,
    Phase2BError,
    _locked_final_series,
    assert_inner_selection_years,
    final_training_allowed_anchor_mask,
    histgb_classifier,
    inner_allowed_anchor_mask,
)
from ecoguard.shared.air_pollution_history import AirPollutionSeriesIdentity
from ecoguard.shared.air_pollution_trend_features import (
    FEATURE_COLUMNS,
    TREND_FEATURE_POLICY_VERSION,
)


def test_inner_split_has_exact_155_minute_boundary_embargo():
    slots = 365 * 288
    train = inner_allowed_anchor_mask(2022, slots)
    validation = inner_allowed_anchor_mask(2023, slots)

    assert train[-31]
    assert not train[-30:].any()
    assert not validation[:31].any()
    assert validation[31]
    assert validation[-31]
    assert not validation[-30:].any()


def test_hyperparameter_selection_rejects_2024_and_2025():
    assert_inner_selection_years(INNER_TRAIN_YEARS, INNER_VALIDATION_YEARS)
    with pytest.raises(Phase2BError, match="2021-2022"):
        assert_inner_selection_years((2021, 2022), (2024,))
    with pytest.raises(Phase2BError, match="2025"):
        assert_inner_selection_years((2021, 2022), (2025,))
    with pytest.raises(Phase2BError, match="2021-2023"):
        inner_allowed_anchor_mask(2024, count=365 * 288)


def test_phase2a_loader_hard_rejects_2025_even_without_matching_files():
    identity = AirPollutionSeriesIdentity("1", "4", "NO2")
    with pytest.raises(Phase2AError, match="2021-2024"):
        load_series(identity, [Path("2025-01.json.gz")], {2025})


def test_identity_vocabulary_is_deterministic_and_non_ordinal():
    first = AirPollutionSeriesIdentity("20", "9", "PM10")
    second = AirPollutionSeriesIdentity("3", "12", "PM10")
    left = IdentityVocabulary.fit([first, second])
    right = IdentityVocabulary.fit([second, first, second])

    assert left == right
    assert left.to_dict()["non_ordinal"] is True
    encoded = left.sparse_one_hot(first, 2)
    assert encoded.shape == (2, left.sparse_width)
    assert np.all(encoded.getnnz(axis=1) == 3)
    assert np.array_equal(encoded.toarray()[0], encoded.toarray()[1])


def test_unseen_identity_uses_explicit_unknown_features():
    known = AirPollutionSeriesIdentity("20", "9", "PM10")
    unseen = AirPollutionSeriesIdentity("999", "888", "PM10")
    vocabulary = IdentityVocabulary.fit([known])
    names = vocabulary.feature_names
    row = vocabulary.sparse_one_hot(unseen, 1).toarray()[0]

    assert row[names.index("station=<UNKNOWN>")] == 1
    assert row[names.index("channel=<UNKNOWN>")] == 1
    assert row[names.index("series=<UNKNOWN>")] == 1
    assert np.isnan(vocabulary.categorical_codes(unseen, 1)).all()


def test_sgd_matrix_controls_weighting_epochs_and_learning_rate():
    by_name = {candidate.name: candidate for candidate in SGD_CANDIDATES}
    assert by_name["phase2a_balanced_optimal_1epoch"].weighted is True
    assert by_name["phase2a_balanced_optimal_1epoch"].include_identity is False
    assert by_name["phase2a_unweighted_optimal_1epoch"].weighted is False
    assert by_name["phase2b_balanced_optimal_1epoch"].include_identity is True
    assert by_name["phase2b_balanced_optimal_3epoch"].epochs == 3
    assert by_name["phase2b_unweighted_constant_3epoch"].learning_rate == "constant"
    assert (
        by_name["phase2b_unweighted_invscaling_3epoch"].learning_rate
        == "invscaling"
    )
    assert all(candidate.classifier().loss == "log_loss" for candidate in SGD_CANDIDATES)


def test_histgb_policy_is_deterministic_and_training_only():
    policy = HistGBMonthlyBlockPolicy()
    assert policy.block_dates((2021, 2022)) == policy.block_dates((2021, 2022))
    assert len(policy.block_dates((2021, 2022, 2023))) == 36
    assert len(set(policy.block_dates((2021, 2022, 2023)))) == 36
    with pytest.raises(Phase2BError, match="2021-2023"):
        policy.day(2024, 1)

    model = histgb_classifier()
    categorical = model.get_params()["categorical_features"]
    assert categorical[-3:].all()
    assert not categorical[:-3].any()

    rng = np.random.default_rng(7)
    features = rng.normal(size=(90, len(categorical)))
    features[:, -3:] = np.column_stack((
        np.arange(90) % 3,
        np.arange(90) % 2,
        np.arange(90) % 6,
    ))
    labels = np.arange(90) % 3
    model.fit(features, labels)
    assert model.predict(features).shape == (90,)


def test_locked_final_sgd_matrix_excludes_pm10_and_matches_selection():
    assert tuple(LOCKED_FINAL_CANDIDATES) == ("NO2", "O3", "PM2.5", "SO2")
    assert FINAL_TRAIN_YEARS == (2021, 2022, 2023)
    assert LOCKED_FINAL_CANDIDATES["NO2"].weighted is True
    assert LOCKED_FINAL_CANDIDATES["NO2"].learning_rate == "optimal"
    for pollutant in ("O3", "PM2.5"):
        candidate = LOCKED_FINAL_CANDIDATES[pollutant]
        assert candidate.weighted is False
        assert candidate.learning_rate == "invscaling"
        assert candidate.eta0 == 0.01
        assert candidate.power_t == 0.25
    assert LOCKED_FINAL_CANDIDATES["SO2"].weighted is False
    assert LOCKED_FINAL_CANDIDATES["SO2"].learning_rate == "optimal"
    assert all(item.epochs == 3 for item in LOCKED_FINAL_CANDIDATES.values())
    assert all(item.include_identity for item in LOCKED_FINAL_CANDIDATES.values())


def test_final_fit_boundary_policy_rejects_2024_and_2025():
    slots = 365 * 288
    first = final_training_allowed_anchor_mask(2021, slots)
    middle = final_training_allowed_anchor_mask(2022, slots)
    last = final_training_allowed_anchor_mask(2023, slots)

    assert not first[:24].any()
    assert first[24]
    assert middle.all()
    assert last[-31]
    assert not last[-30:].any()
    for year in (2024, 2025):
        with pytest.raises(Phase2BError, match="2021-2023"):
            final_training_allowed_anchor_mask(year, slots)


def test_final_series_resolution_only_selects_exact_2021_2023_paths(tmp_path):
    selected_identities = []
    for index, pollutant in enumerate(LOCKED_FINAL_CANDIDATES, start=1):
        identity = {
            "station_id": str(index),
            "channel_id": str(index + 10),
            "pollutant": pollutant,
        }
        selected_identities.append(identity)
        slug = pollutant.lower().replace(".", "_")
        directory = tmp_path / f"station_{index}" / f"channel_{index + 10}_{slug}"
        directory.mkdir(parents=True)
        for year in (2021, 2024, 2025):
            (directory / f"{year}-01.json.gz").touch()

    resolved = _locked_final_series(
        tmp_path,
        {
            "selected_identities": selected_identities,
            "selected_series": {
                pollutant: 1 for pollutant in LOCKED_FINAL_CANDIDATES
            },
        },
    )
    assert len(resolved) == 4
    assert all([path.name for path in paths] == ["2021-01.json.gz"] for _, paths in resolved)


def test_final_joblib_bundle_round_trip_predicts_probabilities(tmp_path):
    identity = AirPollutionSeriesIdentity("1", "4", "NO2")
    values = np.vstack((
        np.zeros(len(FEATURE_COLUMNS)),
        np.ones(len(FEATURE_COLUMNS)),
        np.full(len(FEATURE_COLUMNS), 2.0),
    ))
    scaler = StandardScaler().fit(values)
    vocabulary = IdentityVocabulary.fit([identity])
    candidate = LOCKED_FINAL_CANDIDATES["NO2"]
    classifier = candidate.classifier()
    transformed = np.hstack((
        scaler.transform(values),
        vocabulary.sparse_one_hot(identity, len(values)).toarray(),
    ))
    classifier.partial_fit(
        transformed,
        np.asarray([0, 1, 2]),
        classes=np.arange(3),
    )
    bundle = FinalSGDModelBundle(
        artifact_version=FINAL_ARTIFACT_VERSION,
        model_version="test-v1",
        pollutant="NO2",
        training_start="2021-01-01T00:00:00+02:00",
        training_end="2024-01-01T00:00:00+02:00",
        feature_policy_version=TREND_FEATURE_POLICY_VERSION,
        preprocessing_version=PREPROCESSING_VERSION,
        epsilon_policy={"version": "test", "epsilon": 1.0},
        configuration={"name": candidate.name},
        feature_columns=tuple(FEATURE_COLUMNS),
        labels=("FALLING", "STABLE", "RISING"),
        scaler=scaler,
        identity_vocabulary=vocabulary,
        classifier=classifier,
    )
    path = tmp_path / "model.joblib"
    joblib.dump(bundle, path)
    loaded = joblib.load(path)
    probabilities = loaded.predict_proba(values[:1], identity)

    assert probabilities.shape == (1, 3)
    assert np.isfinite(probabilities).all()
    assert probabilities.sum(axis=1) == pytest.approx([1.0])
    with pytest.raises(ValueError, match="pollutant identity mismatch"):
        loaded.predict_proba(
            values[:1], AirPollutionSeriesIdentity("1", "4", "O3")
        )
