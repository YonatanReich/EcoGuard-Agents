"""EA-319 settlement-ranking tests; corridor and transport time are excluded."""

from math import isfinite

import pytest
from pydantic import TypeAdapter, ValidationError

from agents.air_pollution_transport_schemas import (
    AngularDifferenceDegrees,
    DirectionDegrees,
    SettlementTransportCandidate,
)
from services.air_pollution_settlement_ranking import (
    RANKING_ALGORITHM_VERSION,
    SCORE_METHOD,
    SettlementSpatialRankingResult,
    ZeroDistanceSettlementError,
    rank_settlement_candidates,
)


ORIGIN = {"latitude": 0.0, "longitude": 0.0}
WIND_FROM_WEST = 270.0


def candidate(identifier, latitude, longitude, name=None):
    return {
        "settlement_id": identifier,
        "name": name or identifier,
        "coordinates": {"latitude": latitude, "longitude": longitude},
    }


def ranked(*candidates, origin=ORIGIN, wind_from=WIND_FROM_WEST):
    return rank_settlement_candidates(origin, wind_from, list(candidates))


def test_settlement_directly_downwind_has_full_directional_alignment():
    result = ranked(candidate("east", 0.0, 1.0))[0]
    assert result.bearing_from_origin_deg == pytest.approx(90.0)
    assert result.angular_difference_deg == pytest.approx(0.0)
    assert result.relevance_score == pytest.approx(1.0)
    assert result.along_wind_distance_m == pytest.approx(result.geodesic_distance_m)
    assert result.crosswind_distance_m == pytest.approx(0.0)


def test_settlement_slightly_off_axis_exposes_geometry():
    result = ranked(candidate("north-east", 0.2, 1.0))[0]
    assert 0.0 < result.angular_difference_deg < 90.0
    assert 0.0 < result.relevance_score < 1.0
    assert result.along_wind_distance_m > 0.0
    assert result.crosswind_distance_m > 0.0


def test_perpendicular_settlement_has_zero_along_wind_component():
    result = ranked(candidate("north", 1.0, 0.0))[0]
    assert result.angular_difference_deg == pytest.approx(90.0)
    assert result.along_wind_distance_m == 0.0
    assert result.crosswind_distance_m == pytest.approx(result.geodesic_distance_m)
    assert result.relevance_score == 0.0


def test_directly_upwind_settlement_has_negative_along_wind_component():
    result = ranked(candidate("west", 0.0, -1.0))[0]
    assert result.angular_difference_deg == pytest.approx(180.0)
    assert result.along_wind_distance_m == pytest.approx(-result.geodesic_distance_m)
    assert result.crosswind_distance_m == pytest.approx(0.0)
    assert result.relevance_score == 0.0


def test_multiple_settlements_are_direction_first_ordered():
    results = ranked(
        candidate("upwind", 0.0, -0.2),
        candidate("off-axis", 0.2, 1.0),
        candidate("perpendicular", 1.0, 0.0),
        candidate("downwind", 0.0, 2.0),
    )
    assert [item.settlement_id for item in results] == [
        "downwind",
        "off-axis",
        "perpendicular",
        "upwind",
    ]
    assert [item.rank for item in results] == [1, 2, 3, 4]


def test_closer_distance_breaks_equal_angle_tie():
    results = ranked(
        candidate("far", 0.0, 2.0),
        candidate("near", 0.0, 1.0),
    )
    assert [item.settlement_id for item in results] == ["near", "far"]


def test_stable_id_breaks_complete_geometry_tie():
    results = ranked(
        candidate("settlement-b", 0.0, 1.0),
        candidate("settlement-a", 0.0, 1.0),
    )
    assert [item.settlement_id for item in results] == [
        "settlement-a",
        "settlement-b",
    ]


@pytest.mark.parametrize(
    ("wind_from", "destination", "expected_downwind"),
    [
        (0.0, (-1.0, 0.0), 180.0),
        (90.0, (0.0, -1.0), 270.0),
        (180.0, (1.0, 0.0), 0.0),
        (270.0, (0.0, 1.0), 90.0),
    ],
)
def test_cardinal_wind_directions_rank_matching_downwind_settlement(
    wind_from,
    destination,
    expected_downwind,
):
    latitude, longitude = destination
    result = ranked(
        candidate("target", latitude, longitude),
        wind_from=wind_from,
    )[0]
    assert (wind_from + 180.0) % 360.0 == expected_downwind
    assert result.angular_difference_deg == pytest.approx(0.0)
    assert result.rank == 1


def test_direction_wrap_around_uses_smallest_difference():
    result = ranked(
        candidate("near-north", 0.9848, 0.1736),
        wind_from=170.0,
    )[0]
    assert result.bearing_from_origin_deg == pytest.approx(10.0, abs=0.02)
    assert result.angular_difference_deg == pytest.approx(20.0, abs=0.02)


def test_international_date_line_distance_and_bearing():
    result = ranked(
        candidate("date-line-east", 0.0, -179.9),
        origin={"latitude": 0.0, "longitude": 179.9},
    )[0]
    assert result.bearing_from_origin_deg == pytest.approx(90.0)
    assert result.geodesic_distance_m == pytest.approx(22_239.0, rel=0.001)
    assert result.relevance_score == pytest.approx(1.0)


def test_distance_supports_multiple_hemispheres():
    result = ranked(
        candidate("southern-western", -34.0, -70.0),
        origin={"latitude": -33.0, "longitude": -71.0},
    )[0]
    assert isfinite(result.geodesic_distance_m)
    assert result.geodesic_distance_m > 0.0


def test_zero_distance_settlement_is_explicitly_rejected():
    with pytest.raises(
        ZeroDistanceSettlementError,
        match="directional ranking is undefined",
    ):
        ranked(candidate("at-origin", 0.0, 0.0))


@pytest.mark.parametrize(
    "coordinates",
    [
        {"latitude": 91.0, "longitude": 0.0},
        {"latitude": 0.0, "longitude": -181.0},
    ],
)
def test_invalid_candidate_coordinates_are_rejected(coordinates):
    invalid = {
        "settlement_id": "invalid",
        "name": "invalid",
        "coordinates": coordinates,
    }
    with pytest.raises(ValidationError):
        ranked(invalid)


def test_invalid_origin_is_rejected_even_without_candidates():
    with pytest.raises(ValidationError):
        rank_settlement_candidates(
            {"latitude": 91.0, "longitude": 0.0},
            WIND_FROM_WEST,
            [],
        )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_wind_direction_is_rejected(invalid):
    with pytest.raises(ValueError, match="finite number"):
        ranked(candidate("east", 0.0, 1.0), wind_from=invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_coordinates_are_rejected(invalid):
    with pytest.raises(ValidationError):
        ranked(candidate("invalid", invalid, 1.0))


def test_repeated_rankings_are_deterministic():
    inputs = [
        candidate("second", 0.2, 1.0),
        candidate("first", 0.0, 1.0),
        candidate("third", 0.0, -1.0),
    ]
    serialized = [
        [item.model_dump() for item in ranked(*inputs)]
        for _ in range(10)
    ]
    assert all(result == serialized[0] for result in serialized[1:])


def test_score_is_explicitly_heuristic_and_not_probability():
    result = ranked(candidate("east", 0.0, 1.0))[0]
    fields = set(SettlementSpatialRankingResult.model_fields)
    assert result.score_kind == "heuristic_geometric_relevance"
    assert result.score_method == SCORE_METHOD
    assert result.ranking_algorithm_version == RANKING_ALGORITHM_VERSION
    assert result.score_components.directional_alignment == result.relevance_score
    assert not any("probability" in field for field in fields)
    assert result.potential_downwind_relevance == "indeterminate"
    assert result.exposure_not_confirmed is True


def test_results_are_compatible_with_ea317_and_ea318_constraints():
    source_candidate = SettlementTransportCandidate.model_validate(
        candidate("east", 0.0, 1.0)
    )
    result = ranked(source_candidate)[0]
    assert TypeAdapter(DirectionDegrees).validate_python(
        result.bearing_from_origin_deg
    ) == result.bearing_from_origin_deg
    assert TypeAdapter(AngularDifferenceDegrees).validate_python(
        result.angular_difference_deg
    ) == result.angular_difference_deg
    assert result.settlement_id == source_candidate.settlement_id
    assert RANKING_ALGORITHM_VERSION == "direction-first-v1"


def test_duplicate_stable_ids_are_rejected():
    with pytest.raises(ValueError, match="IDs must be unique"):
        ranked(
            candidate("duplicate", 0.0, 1.0),
            candidate("duplicate", 0.0, 2.0),
        )
