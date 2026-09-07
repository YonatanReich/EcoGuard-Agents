"""EA-309: injected synthetic observations; no live provider or database."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agents.air_pollution_anomaly_detector import (
    AirPollutionAnomalyDetector,
    AirQualityReferenceRule,
    DetectionRequest,
    DetectorConfig,
    HistoricalBaseline,
    ProviderAQIEvidence,
)
from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly, DetectionAssessment
from services.air_quality_schemas import AirQualityObservation

NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
LOCATION = {"latitude": 32.1, "longitude": 34.8}
UNIT = "µg/m³"


def reading(value=10.0, minutes=0, **changes):
    stamp = NOW + timedelta(minutes=minutes)
    payload = dict(
        provider_station_id="station-1", provider_channel_id="channel-1",
        pollutant="PM2.5", value=float(value), unit=UNIT, location=LOCATION,
        observed_at=stamp, provider_timestamp=stamp.isoformat(),
        provider_pollutant_id="provider-pm25", provider_unit="ug/m3",
        provider_status="Valid", provider_status_id="1",
    )
    payload.update(changes)
    return AirQualityObservation(**payload)


def sequence(values=(30, 40, 50), step=5):
    return [reading(value, -(len(values) - 1 - i) * step) for i, value in enumerate(values)]


def request(observations=None, **changes):
    return DetectionRequest(
        station_id="station-1", station_name="Synthetic station",
        pollutant="PM2.5", location=LOCATION,
        observations=observations or [], **changes,
    )


def rule(**changes):
    payload = dict(
        rule_id="synthetic-rule", pollutant="PM2.5", reference_kind="environmental",
        value=20.0, unit=UNIT, averaging_minutes=15, source="synthetic test reference",
        effective_from=NOW - timedelta(days=1), source_version="test-v1",
    )
    payload.update(changes)
    return AirQualityReferenceRule(**payload)


def aqi(**changes):
    payload = dict(
        provider="test-index-source", station_id="station-1", value=-210.0,
        category="provider-test-category", observed_at=NOW, anomalous=True,
        pollutant="PM2.5", pollutant_sub_index=-210.0,
        interpretation_source="synthetic provider-category policy v1",
    )
    payload.update(changes)
    return ProviderAQIEvidence(**payload)


def baseline(**changes):
    payload = dict(
        station_id="station-1", pollutant="PM2.5", unit=UNIT,
        values=[9.0, 10.0, 11.0, 12.0] * 5, source="synthetic history",
        ended_at=NOW - timedelta(days=1), version="history-v1",
    )
    payload.update(changes)
    return HistoricalBaseline(**payload)


def detector(**changes):
    return AirPollutionAnomalyDetector(DetectorConfig(**changes))


def sustained_detector(**changes):
    return detector(sustained_value_threshold=20.0, sustained_unit=UNIT, **changes)


def detect(data, engine=None):
    return (engine or detector()).detect(data, detected_at=NOW)


def test_no_observations_or_unconfigured_normal_reading():
    assert detect(request()) is None
    assert detect(request([reading()])) is None
    assert detect(request(sequence())) is None  # No invented production rule.


def test_isolated_spike_cannot_complete_long_rule_or_persistence():
    data = request([reading(999)], reference_rules=[rule(averaging_minutes=1440)])
    assert detect(data, sustained_detector()) is None


def test_sustained_increasing_sequence_and_auditable_trend():
    result = detect(request(sequence()), sustained_detector(strong_increase_fraction=0.5))
    assert result.assessment.detection_methods == ["sustained_condition"]
    assert any("strong increasing" in item for item in result.anomaly_reasons)
    evidence = next(e for e in result.supporting_evidence if e.evidence_type == "sustained_condition")
    assert evidence.attributes["minimum_persistence_minutes"] == 10
    assert evidence.attributes["unit"] == UNIT


def test_rate_of_change_alone_does_not_trigger():
    assert detect(request(sequence((1, 2, 3))), sustained_detector(strong_increase_fraction=0.1)) is None


def test_persistence_uses_full_run_not_just_minimum_sample_tail():
    engine = sustained_detector(minimum_persistence_minutes=20)
    assert detect(request(sequence()), engine) is None
    assert detect(request(sequence((30, 35, 40, 45, 50))), engine) is not None


@pytest.mark.parametrize("status", ["NoData", "Down", "InVld", "Calib", "invalid", "calibration"])
def test_invalid_status_breaks_sequence(status):
    values = sequence()
    values[1] = reading(40, -5, provider_status=status)
    assert detect(request(values), sustained_detector()) is None


def test_missing_sample_and_latest_invalid_sample_break_sequence():
    assert detect(request([reading(30, -15), reading(40, -5), reading(50)]), sustained_detector()) is None
    values = sequence() + [reading(60, 1, provider_status="Down")]
    assert sustained_detector().detect(request(values), detected_at=NOW + timedelta(minutes=1)) is None


def test_equal_values_can_be_sustained_without_trend():
    result = detect(request(sequence((40, 40, 40))), sustained_detector(strong_increase_fraction=0.1))
    assert result is not None
    assert not any("strong increasing" in item for item in result.anomaly_reasons)


def test_complete_reference_mean_counts_and_exact_boundary():
    values = [reading(900, -15), *sequence((30, 40, 50))]
    window = detector().evaluate_reference_window(rule(), tuple(values))
    assert window.average == 40.0  # Start boundary excluded, no influence from 900.
    assert len(window.observations) == window.expected == 3
    assert window.completeness == 1.0 and window.complete and window.exceeded
    result = detect(request(values, reference_rules=[rule()]))
    assert result.assessment.aggregation_minutes == 15
    assert result.assessment.reference_version == "test-v1"


def test_incomplete_window_is_provisional_and_not_zero_filled():
    values = [reading(30, -10), reading(50)]
    window = detector().evaluate_reference_window(rule(), tuple(values))
    assert window.average == 40.0
    assert len(window.observations) == 2 and window.expected == 3
    assert window.completeness == pytest.approx(2 / 3)
    assert not window.complete and not window.exceeded
    assert detect(request(values, reference_rules=[rule()])) is None
    result = detect(request(values, reference_rules=[rule()], provider_aqi=aqi()))
    assert result.assessment.window_complete is False
    assert "reference_threshold" not in result.assessment.detection_methods
    assert any("incomplete" in text for text in result.assessment.limitations)


def test_coverage_requires_window_span_and_supports_configured_missing_fraction():
    engine = detector(minimum_completeness=0.75)
    values = (reading(40, -15), reading(40, -10), reading(40))
    window = engine.evaluate_reference_window(rule(averaging_minutes=20), values)
    assert window.complete and window.completeness == 0.75
    recent_only = tuple(sequence((40, 40, 40)))
    assert not engine.evaluate_reference_window(rule(averaging_minutes=20), recent_only).complete


def test_duplicate_observations_cannot_inflate_completeness():
    window = detector().evaluate_reference_window(rule(), (reading(100),) * 10)
    assert len(window.observations) == 1
    assert window.completeness == pytest.approx(1 / 3)
    assert not window.exceeded


def test_conflicting_duplicates_are_excluded():
    values = sequence() + [reading(999, -5)]
    assert detect(request(values), sustained_detector()) is None
    result = detect(request(values, provider_aqi=aqi()))
    assert result.sources[0].metadata["excluded_count"] == 2


def test_dense_or_incompatible_cadence_cannot_complete_reference():
    dense = tuple(sequence((40,) * 15, step=1))
    assert not detector().evaluate_reference_window(rule(), dense).complete
    assert not detector().evaluate_reference_window(rule(averaging_minutes=7), tuple(sequence())).complete


@pytest.mark.parametrize("kind", ["target", "environmental", "alert", "other"])
def test_reference_kinds_preserved_without_downstream_decisions(kind):
    result = detect(request(sequence(), reference_rules=[rule(reference_kind=kind)]))
    assert result.assessment.reference_kind == kind
    assert kind in result.explanation
    assert not {"emergency_required", "dispatch", "human_life_risk_score", "response_actions"} & result.model_dump().keys()


def test_future_rule_and_unit_mismatch_do_not_trigger():
    assert detect(request(sequence(), reference_rules=[rule(effective_from=NOW)])) is None
    assert detect(request(sequence(), reference_rules=[rule(unit="ppm")])) is None
    assert detect(request(sequence(), reference_rules=[rule(value=40.0)])) is None  # Equality is not exceedance.


def test_sustained_threshold_requires_matching_explicit_unit():
    with pytest.raises(ValidationError):
        DetectorConfig(sustained_value_threshold=20.0)
    engine = detector(sustained_value_threshold=20.0, sustained_unit="ppm")
    assert detect(request(sequence()), engine) is None


def test_reference_mismatch_evidence_preserves_original_aggregate_unit():
    result = detect(request(sequence(), reference_rules=[rule(unit="ppm")], provider_aqi=aqi()))
    evidence = next(e for e in result.supporting_evidence if e.evidence_type == "reference_window")
    assert evidence.attributes["aggregate"] == 40.0
    assert evidence.attributes["aggregate_unit"] == UNIT
    assert evidence.attributes["reference_unit"] == "ppm"
    assert evidence.attributes["exceeded"] is False


def test_aqi_value_and_subindex_preserved_without_breakpoint_calculation():
    result = detect(request([reading()], provider_aqi=aqi()))
    assert result.assessment.provider_aqi_value == -210.0
    evidence = next(e for e in result.supporting_evidence if e.evidence_type == "provider_aqi")
    assert evidence.attributes["pollutant_sub_index"] == -210.0
    assert evidence.attributes["category"] == "provider-test-category"
    assert result.confidence <= 0.45
    assert detect(request([reading()], provider_aqi=aqi(value=-999.0, anomalous=False))) is None


@pytest.mark.parametrize("minutes", [-11, 1])
def test_stale_or_future_aqi_cannot_trigger(minutes):
    assert detect(request([reading()], provider_aqi=aqi(observed_at=NOW + timedelta(minutes=minutes)))) is None


@pytest.mark.parametrize("field,value", [("station_id", "other"), ("pollutant", "NO2")])
def test_mismatched_aqi_rejected(field, value):
    with pytest.raises(ValidationError):
        request([reading()], provider_aqi=aqi(**{field: value}))


def test_robust_baseline_is_not_reference_exceedance():
    result = detect(request([reading(50)], historical_baseline=baseline()))
    assert result.assessment.detection_methods == ["historical_baseline"]
    assert result.assessment.baseline_median == 10.5
    assert result.assessment.baseline_deviation == 39.5
    assert result.assessment.reference_kind is None
    assert result.confidence <= 0.45
    assert detect(request([reading(10)], historical_baseline=baseline())) is None


def test_old_history_does_not_defeat_isolated_sample_confidence_cap():
    values = [reading(10, -120), reading(10, -60), reading(50)]
    result = detect(request(values, historical_baseline=baseline(), provider_aqi=aqi()))
    assert result.confidence <= 0.45


@pytest.mark.parametrize("changes", [
    {"values": [9.0, 10.0]}, {"values": [10.0] * 20},
    {"unit": "ppm"}, {"ended_at": NOW},
])
def test_unusable_baseline_has_no_trigger(changes):
    assert detect(request([reading(50)], historical_baseline=baseline(**changes))) is None


@pytest.mark.parametrize("values", [[float("nan")], [float("inf")], [-1.0], ["10"], [True]])
def test_malformed_baseline_rejected(values):
    with pytest.raises(ValidationError):
        baseline(values=values)


@pytest.mark.parametrize("changes", [{"valid": False}, {"value": -9999.0}, {"quality_control": "invalid"}])
def test_invalid_normalized_observation_rejected(changes):
    with pytest.raises(ValidationError):
        reading(**changes)


def test_mutated_model_is_revalidated():
    invalid = reading().model_copy(update={"value": -9999.0})
    with pytest.raises(ValidationError):
        detect(request([invalid]))


def test_stale_future_and_inactive_observations_do_not_trigger():
    assert detect(request([reading(100, -11)], provider_aqi=aqi())) is None
    assert detect(request([reading(100, 1)], provider_aqi=aqi())) is None
    for field in ("station_active", "channel_active"):
        assert detect(request(sequence(), provider_aqi=aqi(), **{field: False})) is None


def test_detection_clock_requires_timezone():
    with pytest.raises(ValueError, match="timezone"):
        detector().detect(request([reading()]), detected_at=NOW.replace(tzinfo=None))


def test_confidence_is_auditable_and_configured_preliminary_cap_applies():
    data = request(sequence(), reference_rules=[rule()], provider_aqi=aqi(), historical_baseline=baseline())
    result = detect(data, sustained_detector(preliminary_confidence_cap=0.6))
    assessment = result.assessment
    assert assessment.preliminary
    assert result.confidence == 0.6
    assert assessment.confidence_factors["preliminary_data_penalty"] < 0
    assert assessment.confidence_caps["preliminary_data"] == 0.6
    reconstructed = min(max(sum(assessment.confidence_factors.values()), 0), *assessment.confidence_caps.values())
    assert result.confidence == pytest.approx(reconstructed)


def test_incomplete_window_reduces_confidence_with_same_aqi():
    data = sequence()
    complete = detect(request(data, provider_aqi=aqi()))
    incomplete = detect(request(data, provider_aqi=aqi(), reference_rules=[rule(averaging_minutes=1440)]))
    assert incomplete.confidence < complete.confidence


def test_output_contract_provenance_round_trip_and_repeatability():
    data = request(sequence(), reference_rules=[rule()], provider_aqi=aqi(), historical_baseline=baseline())
    result = detect(data)
    assert AirPollutionAnomaly.model_validate_json(result.model_dump_json()) == result
    assert result == detect(data)
    assert {e.source_id for e in result.supporting_evidence} <= {s.source_id for s in result.sources}
    assert result.sources[0].metadata["channel_id"] == "channel-1"
    assert all(o.provider_unit == "ug/m3" for o in result.pollutant_observations)


def test_optional_assessment_validation():
    with pytest.raises(ValidationError):
        DetectionAssessment(valid_sample_count=2, expected_sample_count=4, completeness_ratio=1.0)
    with pytest.raises(ValidationError):
        DetectionAssessment(window_started_at=NOW, window_ended_at=NOW - timedelta(minutes=1))
    with pytest.raises(ValidationError):
        DetectionAssessment(reference_value=20.0)


def test_mixed_channels_and_units_cannot_be_averaged():
    for changes in ({"provider_channel_id": "other"}, {"unit": "ppm"}):
        with pytest.raises(ValidationError):
            request([reading(30, -5), reading(40, **changes)])
