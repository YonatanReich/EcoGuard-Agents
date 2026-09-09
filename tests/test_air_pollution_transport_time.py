"""EA-321 kinematic duration tests; no ETA or arrival-time calculations."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agents.air_pollution_transport_schemas import WindEvidence
from services.air_pollution_settlement_ranking import rank_settlement_candidates
from services.air_pollution_transport_corridor import apply_transport_corridor
from services.air_pollution_transport_time import (
    TRANSPORT_TIME_ASSUMPTIONS,
    KinematicTransportTimeEstimate,
    apply_transport_time_estimate,
    estimate_corridor_settlement_transport_time,
    estimate_kinematic_transport_time,
)


def estimate(distance=1_000.0, speed=5.0, **changes):
    return estimate_kinematic_transport_time(
        distance,
        speed,
        wind_evidence_suitability=changes.pop("suitability", "usable"),
        minimum_wind_speed_mps=changes.pop("minimum", None),
        **changes,
    )


def wind_evidence(**changes):
    observed_at = datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc)
    payload = {
        "evidence_id": "wind:test",
        "provider": "normalized-test-provider",
        "source_type": "station_observation",
        "provider_location_kind": "station",
        "provider_location_id": "station-1",
        "requested_coordinates": {"latitude": 32.1, "longitude": 34.8},
        "actual_provider_coordinates": {"latitude": 32.11, "longitude": 34.81},
        "raw_provider_timestamp": "2026-09-09T11:00:00+02:00",
        "wind_observed_at": observed_at,
        "retrieved_at": observed_at,
        "wind_from_direction_deg": 270.0,
        "wind_speed_mps": 4.0,
        "gust_speed_mps": 99.0,
        "provider_validity": "valid",
        "original_units": {
            "wind_direction": "degrees",
            "wind_speed": "m/s",
            "gust_speed": "m/s",
        },
        "time_offset_from_anomaly_seconds": 0.0,
    }
    payload.update(changes)
    return payload


def corridor_settlement(latitude=0.0, longitude=1.0, **corridor_changes):
    ranked = rank_settlement_candidates(
        {"latitude": 0.0, "longitude": 0.0},
        270.0,
        [{
            "settlement_id": "settlement-1",
            "name": "Settlement 1",
            "coordinates": {"latitude": latitude, "longitude": longitude},
        }],
    )
    corridor = apply_transport_corridor(
        ranked,
        downwind_to_direction_deg=90.0,
        corridor_half_angle_deg=corridor_changes.pop("half_angle", 30.0),
        max_screening_distance_m=corridor_changes.pop("max_distance", 500_000.0),
        corridor_method="fixed_angle_screening",
        **corridor_changes,
    )
    return corridor.settlement_results[0]


def test_basic_calculation_returns_seconds():
    result = estimate()
    assert result.estimate_status == "estimated"
    assert result.kinematic_advection_time_seconds == 200.0


def test_fractional_wind_speed_is_supported():
    assert estimate(speed=2.5).kinematic_advection_time_seconds == 400.0


def test_large_distance_is_supported():
    result = estimate(distance=10_000_000.0, speed=10.0)
    assert result.kinematic_advection_time_seconds == 1_000_000.0


def test_very_small_positive_wind_has_no_implicit_calm_threshold():
    result = estimate(distance=100.0, speed=0.001)
    assert result.estimate_status == "estimated"
    assert result.kinematic_advection_time_seconds == 100_000.0


def test_zero_wind_suppresses_estimate():
    result = estimate(speed=0.0)
    assert result.estimate_status == "suppressed"
    assert result.kinematic_advection_time_seconds is None
    assert result.suppression_reason == "zero_or_nonpositive_wind_speed"


def test_negative_wind_is_rejected():
    with pytest.raises(ValidationError):
        estimate(speed=-0.1)


def test_zero_along_wind_distance_suppresses_estimate():
    result = estimate(distance=0.0)
    assert result.suppression_reason == "zero_or_nonpositive_along_wind_distance"
    assert result.kinematic_advection_time_seconds is None


def test_near_zero_positive_along_wind_distance_remains_eligible():
    result = estimate(distance=1e-9, speed=2.0)
    assert result.estimate_status == "estimated"
    assert result.kinematic_advection_time_seconds == pytest.approx(5e-10)


def test_negative_along_wind_distance_is_not_downwind():
    result = estimate(distance=-100.0)
    assert result.estimate_status == "suppressed"
    assert result.suppression_reason == "settlement_not_downwind"


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_wind_speed_is_rejected(invalid):
    with pytest.raises(ValidationError):
        estimate(speed=invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_along_wind_distance_is_rejected(invalid):
    with pytest.raises(ValidationError):
        estimate(distance=invalid)


def test_explicit_minimum_wind_speed_suppresses_below_threshold():
    result = estimate(speed=1.9, minimum=2.0)
    assert result.estimate_status == "suppressed"
    assert result.suppression_reason == "below_explicit_minimum_wind_speed"
    assert result.minimum_wind_speed_mps == 2.0


def test_exact_minimum_wind_speed_is_eligible():
    result = estimate(speed=2.0, minimum=2.0)
    assert result.estimate_status == "estimated"
    assert result.kinematic_advection_time_seconds == 500.0


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_explicit_minimum_is_rejected(invalid):
    with pytest.raises(ValidationError):
        estimate(minimum=invalid)


def test_insufficient_wind_evidence_suppresses_estimate():
    result = estimate(suitability="insufficient")
    assert result.suppression_reason == "insufficient_wind_evidence"


def test_assumptions_are_explicitly_exposed():
    result = estimate()
    assert result.transport_time_assumptions == list(TRANSPORT_TIME_ASSUMPTIONS)
    assert len(result.transport_time_assumptions) == 8
    joined = " ".join(result.transport_time_assumptions).lower()
    for concept in [
        "constant",
        "surface wind",
        "dispersion",
        "plume rise",
        "deposition",
        "chemistry",
        "terrain",
        "monitoring location",
    ]:
        assert concept in joined


def test_method_matches_ea317_contract_value():
    result = estimate()
    assert result.transport_time_method == "constant_wind_kinematic_screening"


def test_suppressed_estimate_is_nullable_and_has_no_method():
    result = estimate(speed=0.0)
    assert result.kinematic_advection_time_seconds is None
    assert result.transport_time_method is None
    assert result.transport_time_assumptions


def test_no_eta_arrival_or_probability_fields_exist():
    fields = set(KinematicTransportTimeEstimate.model_fields)
    forbidden = ("eta", "arrival", "exposure_time", "probability", "impact_time")
    assert not any(term in field for field in fields for term in forbidden)
    assert "kinematic_advection_time_seconds" in fields


def test_repeated_outputs_are_deterministic():
    outputs = [estimate().model_dump() for _ in range(10)]
    assert all(output == outputs[0] for output in outputs[1:])


def test_estimate_can_be_applied_to_ea317_settlement_result():
    settlement = corridor_settlement()
    screening = estimate(
        distance=settlement.along_wind_distance_m,
        speed=4.0,
    )
    result = apply_transport_time_estimate(settlement, screening)
    assert result.kinematic_advection_time_seconds == screening.kinematic_advection_time_seconds
    assert result.transport_time_method == "constant_wind_kinematic_screening"
    assert result.transport_time_assumptions == screening.transport_time_assumptions


def test_suppressed_estimate_keeps_ea317_time_fields_empty():
    settlement = corridor_settlement()
    result = apply_transport_time_estimate(settlement, estimate(speed=0.0))
    assert result.kinematic_advection_time_seconds is None
    assert result.transport_time_method is None
    assert result.transport_time_assumptions == []


def test_estimate_cannot_be_applied_to_different_settlement_geometry():
    settlement = corridor_settlement()
    screening = estimate(
        distance=settlement.along_wind_distance_m + 1.0,
        speed=4.0,
    )
    with pytest.raises(ValueError, match="does not match settlement geometry"):
        apply_transport_time_estimate(settlement, screening)


def test_estimate_cannot_be_applied_to_corridor_excluded_settlement():
    settlement = corridor_settlement(latitude=1.0, longitude=1.0, half_angle=10.0)
    screening = estimate(
        distance=settlement.along_wind_distance_m,
        speed=4.0,
    )
    with pytest.raises(ValueError, match="corridor-excluded settlement"):
        apply_transport_time_estimate(settlement, screening)


def test_full_wind_evidence_uses_normalized_speed_not_gust():
    settlement = corridor_settlement()
    result = estimate_corridor_settlement_transport_time(
        settlement,
        wind_evidence(),
        wind_evidence_suitability="usable",
    )
    assert result.wind_speed_mps == 4.0
    assert result.kinematic_advection_time_seconds == pytest.approx(
        settlement.along_wind_distance_m / 4.0
    )


def test_provider_invalid_wind_evidence_is_suppressed():
    result = estimate_corridor_settlement_transport_time(
        corridor_settlement(),
        wind_evidence(provider_validity="invalid"),
        wind_evidence_suitability="usable",
    )
    assert result.suppression_reason == "insufficient_wind_evidence"


def test_full_wind_evidence_requires_valid_timestamp_semantics():
    payload = wind_evidence(wind_observed_at=datetime(2026, 9, 9, 9, 0))
    with pytest.raises(ValidationError):
        estimate_corridor_settlement_transport_time(
            corridor_settlement(),
            payload,
            wind_evidence_suitability="usable",
        )


def test_non_corridor_settlement_is_suppressed():
    settlement = corridor_settlement(latitude=1.0, longitude=1.0, half_angle=10.0)
    result = estimate_corridor_settlement_transport_time(
        settlement,
        wind_evidence(),
        wind_evidence_suitability="usable",
    )
    assert result.suppression_reason == "settlement_not_in_transport_corridor"


def test_upwind_corridor_exclusion_is_not_given_a_time():
    settlement = corridor_settlement(longitude=-1.0)
    result = estimate_corridor_settlement_transport_time(
        settlement,
        wind_evidence(),
        wind_evidence_suitability="usable",
    )
    assert result.suppression_reason == "settlement_not_downwind"


def test_models_have_no_provider_or_runtime_dependencies():
    fields = set(KinematicTransportTimeEstimate.model_fields)
    assert "provider" not in fields
    assert "runtime" not in fields
    assert WindEvidence.model_validate(wind_evidence()).wind_speed_mps == 4.0
