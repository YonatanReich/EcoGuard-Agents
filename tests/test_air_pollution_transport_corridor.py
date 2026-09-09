"""EA-320 potential-transport corridor tests; no plume or time modeling."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from agents.air_pollution_transport_schemas import SettlementTransportRelevanceResult
from services.air_pollution_settlement_ranking import rank_settlement_candidates
from services.air_pollution_transport_corridor import (
    TransportCorridorScreeningResult,
    apply_transport_corridor,
    corridor_boundary_bearings,
    unavailable_transport_corridor,
)


ORIGIN = {"latitude": 0.0, "longitude": 0.0}
DOWNWIND_EAST = 90.0
WIND_FROM_WEST = 270.0


def candidate(identifier, latitude, longitude):
    return {
        "settlement_id": identifier,
        "name": identifier,
        "coordinates": {"latitude": latitude, "longitude": longitude},
    }


def rankings(*candidates, origin=ORIGIN, wind_from=WIND_FROM_WEST):
    return rank_settlement_candidates(origin, wind_from, list(candidates))


def corridor(
    spatial_rankings,
    *,
    direction=DOWNWIND_EAST,
    half_angle=30.0,
    max_distance=500_000.0,
    method="fixed_angle_screening",
    direction_stddev=None,
):
    return apply_transport_corridor(
        spatial_rankings,
        downwind_to_direction_deg=direction,
        corridor_half_angle_deg=half_angle,
        max_screening_distance_m=max_distance,
        corridor_method=method,
        direction_stddev_deg=direction_stddev,
    )


def test_directly_downwind_settlement_is_inside():
    result = corridor(rankings(candidate("east", 0.0, 1.0))).settlement_results[0]
    assert result.inside_transport_corridor is True
    assert result.exclusion_reason is None
    assert result.rank == 1
    assert result.potential_downwind_relevance == "indeterminate"


def test_slightly_off_axis_settlement_is_inside():
    result = corridor(rankings(candidate("off-axis", 0.2, 1.0))).settlement_results[0]
    assert 0.0 < result.angular_difference_deg < 30.0
    assert result.inside_transport_corridor is True


def test_exact_angular_boundary_is_inclusive():
    spatial = rankings(candidate("boundary", 0.5, 1.0))
    result = corridor(
        spatial,
        half_angle=spatial[0].angular_difference_deg,
    ).settlement_results[0]
    assert result.inside_transport_corridor is True


def test_just_outside_angular_boundary_is_excluded():
    spatial = rankings(candidate("outside-angle", 0.5, 1.0))
    result = corridor(
        spatial,
        half_angle=spatial[0].angular_difference_deg - 0.000001,
    ).settlement_results[0]
    assert result.inside_transport_corridor is False
    assert result.exclusion_reason == "outside_transport_corridor"
    assert result.potential_downwind_relevance == "outside_screening_corridor"


def test_exact_maximum_distance_is_inclusive():
    spatial = rankings(candidate("distance-boundary", 0.0, 1.0))
    result = corridor(
        spatial,
        max_distance=spatial[0].geodesic_distance_m,
    ).settlement_results[0]
    assert result.inside_transport_corridor is True


def test_beyond_maximum_distance_has_specific_exclusion():
    spatial = rankings(candidate("too-far", 0.0, 1.0))
    result = corridor(
        spatial,
        max_distance=spatial[0].geodesic_distance_m - 0.001,
    ).settlement_results[0]
    assert result.inside_transport_corridor is False
    assert result.exclusion_reason == "beyond_screening_range"


def test_directly_upwind_settlement_has_specific_exclusion():
    result = corridor(rankings(candidate("west", 0.0, -1.0))).settlement_results[0]
    assert result.inside_transport_corridor is False
    assert result.exclusion_reason == "upwind_of_origin"


def test_perpendicular_settlement_is_outside_corridor():
    result = corridor(rankings(candidate("north", 1.0, 0.0))).settlement_results[0]
    assert result.along_wind_distance_m == 0.0
    assert result.inside_transport_corridor is False
    assert result.exclusion_reason == "outside_transport_corridor"


def test_wrap_around_corridor_boundaries_are_normalized():
    spatial = rankings(
        candidate("near-north", 0.9848, 0.1736),
        wind_from=170.0,
    )
    result = corridor(
        spatial,
        direction=350.0,
        half_angle=20.1,
    )
    assert result.settlement_results[0].inside_transport_corridor is True
    assert result.boundary_bearings.counterclockwise_boundary_bearing_deg == pytest.approx(
        329.9
    )
    assert result.boundary_bearings.clockwise_boundary_bearing_deg == pytest.approx(10.1)


def test_multiple_settlements_keep_inside_ranks_and_exclude_others():
    result = corridor(
        rankings(
            candidate("upwind", 0.0, -1.0),
            candidate("inside", 0.0, 1.0),
            candidate("off-angle", 1.0, 1.0),
        ),
        half_angle=30.0,
    )
    by_id = {item.settlement_id: item for item in result.settlement_results}
    assert by_id["inside"].rank == 1
    assert by_id["inside"].inside_transport_corridor is True
    assert by_id["off-angle"].rank is None
    assert by_id["off-angle"].exclusion_reason == "outside_transport_corridor"
    assert by_id["upwind"].rank is None
    assert by_id["upwind"].exclusion_reason == "upwind_of_origin"


def test_very_narrow_corridor_accepts_exact_centerline():
    result = corridor(
        rankings(candidate("centerline", 0.0, 1.0)),
        half_angle=0.000001,
    )
    assert result.settlement_results[0].inside_transport_corridor is True


def test_large_valid_half_angle_still_rejects_upwind_component():
    result = corridor(
        rankings(candidate("upwind", 0.0, -1.0)),
        half_angle=179.999,
    )
    assert result.settlement_results[0].exclusion_reason == "upwind_of_origin"


@pytest.mark.parametrize("invalid", [-1.0, 0.0, 180.0, 360.0])
def test_invalid_corridor_half_angle_is_rejected(invalid):
    with pytest.raises(ValidationError):
        corridor(rankings(candidate("east", 0.0, 1.0)), half_angle=invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_corridor_half_angle_is_rejected(invalid):
    with pytest.raises(ValidationError):
        corridor(rankings(candidate("east", 0.0, 1.0)), half_angle=invalid)


@pytest.mark.parametrize("invalid", [-1.0, 360.0, float("nan"), float("inf")])
def test_invalid_downwind_direction_is_rejected(invalid):
    with pytest.raises(ValidationError):
        corridor(rankings(candidate("east", 0.0, 1.0)), direction=invalid)


@pytest.mark.parametrize("invalid", [-1.0, 0.0])
def test_invalid_maximum_distance_is_rejected(invalid):
    with pytest.raises(ValidationError):
        corridor(rankings(candidate("east", 0.0, 1.0)), max_distance=invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_maximum_distance_is_rejected(invalid):
    with pytest.raises(ValidationError):
        corridor(rankings(candidate("east", 0.0, 1.0)), max_distance=invalid)


def test_direction_variability_is_preserved_without_deriving_half_angle():
    result = corridor(
        rankings(candidate("east", 0.0, 1.0)),
        half_angle=17.0,
        method="direction_variability_screening",
        direction_stddev=8.25,
    )
    assert result.parameters.corridor_half_angle_deg == 17.0
    assert result.parameters.direction_stddev_deg == 8.25
    assert result.parameters.corridor_method == "direction_variability_screening"


def test_unavailable_direction_does_not_fabricate_corridor():
    result = unavailable_transport_corridor(
        corridor_half_angle_deg=20.0,
        max_screening_distance_m=50_000.0,
        corridor_method="fixed_angle_screening",
        limitation="Wind direction unavailable from normalized evidence.",
    )
    assert result.data_status == "unavailable"
    assert result.downwind_to_direction_deg is None
    assert result.boundary_bearings is None
    assert result.settlement_results == []
    assert result.potential_downwind_relevance == "indeterminate"


def test_repeated_corridor_output_is_deterministic():
    spatial = rankings(
        candidate("east", 0.0, 1.0),
        candidate("north-east", 0.2, 1.0),
        candidate("west", 0.0, -1.0),
    )
    outputs = [corridor(spatial).model_dump() for _ in range(10)]
    assert all(output == outputs[0] for output in outputs[1:])


def test_output_uses_ea317_settlement_contract_and_ea319_values():
    spatial = rankings(candidate("east", 0.0, 1.0))
    result = corridor(spatial).settlement_results[0]
    assert isinstance(result, SettlementTransportRelevanceResult)
    assert result.geodesic_distance_m == spatial[0].geodesic_distance_m
    assert result.bearing_from_origin_deg == spatial[0].bearing_from_origin_deg
    assert result.angular_difference_deg == spatial[0].angular_difference_deg
    assert result.along_wind_distance_m == spatial[0].along_wind_distance_m
    assert result.crosswind_distance_m == spatial[0].crosswind_distance_m


def test_no_probability_or_confirmed_exposure_semantics():
    fields = set(TransportCorridorScreeningResult.model_fields)
    assert not any("probability" in field for field in fields)
    assert not any("affected" in field or "exposed" in field for field in fields)
    assert corridor(rankings(candidate("east", 0.0, 1.0))).exposure_not_confirmed


def test_no_transport_time_is_introduced():
    result = corridor(rankings(candidate("east", 0.0, 1.0))).settlement_results[0]
    assert result.kinematic_advection_time_seconds is None
    assert result.transport_time_method is None
    assert result.transport_time_assumptions == []


def test_duplicate_settlement_ids_are_rejected():
    spatial = rankings(
        candidate("first", 0.0, 1.0),
        candidate("second", 0.0, 2.0),
    )
    duplicate = spatial[1].model_copy(update={"settlement_id": "first"})
    with pytest.raises(ValueError, match="IDs must be unique"):
        corridor([spatial[0], duplicate])


def test_corridor_does_not_mutate_ea319_results():
    spatial = rankings(candidate("east", 0.0, 1.0))
    before = deepcopy(spatial)
    corridor(spatial)
    assert spatial == before


def test_mismatched_centerline_and_ranking_are_rejected():
    spatial = rankings(candidate("east", 0.0, 1.0))
    with pytest.raises(ValueError, match="does not match the corridor centerline"):
        corridor(spatial, direction=0.0)


def test_boundary_helper_validates_and_normalizes_directions():
    boundaries = corridor_boundary_bearings(5.0, 10.0)
    assert boundaries.counterclockwise_boundary_bearing_deg == 355.0
    assert boundaries.centerline_bearing_deg == 5.0
    assert boundaries.clockwise_boundary_bearing_deg == 15.0
