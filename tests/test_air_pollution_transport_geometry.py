"""EA-318 deterministic transport geometry tests; no ranking or corridor logic."""

from math import isfinite

import pytest
from pydantic import TypeAdapter, ValidationError

from agents.air_pollution_anomaly_schemas import GeographicCoordinate
from agents.air_pollution_transport_schemas import DirectionDegrees
from services.air_pollution_transport_geometry import (
    UndefinedBearingError,
    downwind_to_direction_deg,
    initial_bearing_deg,
    smallest_angular_difference_deg,
)


@pytest.mark.parametrize(
    ("wind_from", "expected_downwind"),
    [(0.0, 180.0), (90.0, 270.0), (180.0, 0.0), (270.0, 90.0)],
)
def test_downwind_conversion_for_cardinal_directions(wind_from, expected_downwind):
    assert downwind_to_direction_deg(wind_from) == expected_downwind


def test_downwind_conversion_wraps_wind_from_359_degrees():
    assert downwind_to_direction_deg(359.0) == 179.0


@pytest.mark.parametrize(
    ("destination", "expected_bearing"),
    [
        ({"latitude": 1.0, "longitude": 0.0}, 0.0),
        ({"latitude": 0.0, "longitude": 1.0}, 90.0),
        ({"latitude": -1.0, "longitude": 0.0}, 180.0),
        ({"latitude": 0.0, "longitude": -1.0}, 270.0),
    ],
)
def test_initial_bearing_for_cardinal_destinations(destination, expected_bearing):
    bearing = initial_bearing_deg(
        {"latitude": 0.0, "longitude": 0.0},
        destination,
    )
    assert bearing == pytest.approx(expected_bearing, abs=1e-12)


def test_initial_bearing_is_normalized_below_360():
    bearing = initial_bearing_deg(
        {"latitude": 0.0, "longitude": 0.0},
        {"latitude": 1.0, "longitude": -1.0},
    )
    assert 270.0 < bearing < 360.0


@pytest.mark.parametrize(
    ("settlement_bearing", "downwind", "expected"),
    [
        (90.0, 90.0, 0.0),
        (100.0, 90.0, 10.0),
        (10.0, 350.0, 20.0),
        (350.0, 10.0, 20.0),
        (180.0, 0.0, 180.0),
    ],
)
def test_smallest_angular_difference(
    settlement_bearing,
    downwind,
    expected,
):
    assert smallest_angular_difference_deg(settlement_bearing, downwind) == expected


def test_identical_coordinates_raise_undefined_bearing():
    point = {"latitude": 32.1, "longitude": 34.8}
    with pytest.raises(UndefinedBearingError, match="identical coordinates"):
        initial_bearing_deg(point, point)


def test_antipodal_coordinates_raise_undefined_bearing():
    with pytest.raises(UndefinedBearingError, match="unique initial bearing"):
        initial_bearing_deg(
            {"latitude": 0.0, "longitude": 0.0},
            {"latitude": 0.0, "longitude": 180.0},
        )


@pytest.mark.parametrize(
    "coordinate",
    [
        {"latitude": -90.1, "longitude": 34.8},
        {"latitude": 90.1, "longitude": 34.8},
    ],
)
def test_invalid_latitude_is_rejected(coordinate):
    with pytest.raises(ValidationError):
        initial_bearing_deg(coordinate, {"latitude": 32.2, "longitude": 34.9})


@pytest.mark.parametrize(
    "coordinate",
    [
        {"latitude": 32.1, "longitude": -180.1},
        {"latitude": 32.1, "longitude": 180.1},
    ],
)
def test_invalid_longitude_is_rejected(coordinate):
    with pytest.raises(ValidationError):
        initial_bearing_deg(coordinate, {"latitude": 32.2, "longitude": 34.9})


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_direction_is_rejected(invalid):
    with pytest.raises(ValueError, match="finite number"):
        downwind_to_direction_deg(invalid)
    with pytest.raises(ValueError, match="finite number"):
        smallest_angular_difference_deg(90.0, invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_coordinate_is_rejected(invalid):
    with pytest.raises(ValidationError):
        initial_bearing_deg(
            {"latitude": invalid, "longitude": 34.8},
            {"latitude": 32.2, "longitude": 34.9},
        )


def test_mutated_coordinate_model_is_revalidated():
    origin = GeographicCoordinate(latitude=32.1, longitude=34.8)
    origin.latitude = float("nan")
    with pytest.raises(ValidationError):
        initial_bearing_deg(origin, GeographicCoordinate(latitude=32.2, longitude=34.9))


@pytest.mark.parametrize("invalid", [-0.1, 360.0, 720.0])
def test_out_of_range_direction_is_rejected(invalid):
    with pytest.raises(ValueError, match="0 <= degrees < 360"):
        downwind_to_direction_deg(invalid)


def test_bearing_crosses_international_date_line_eastward():
    bearing = initial_bearing_deg(
        {"latitude": 0.0, "longitude": 179.9},
        {"latitude": 0.0, "longitude": -179.9},
    )
    assert bearing == pytest.approx(90.0, abs=1e-10)


def test_bearing_supports_southern_and_western_hemispheres():
    bearing = initial_bearing_deg(
        {"latitude": -33.9, "longitude": -70.7},
        {"latitude": -34.9, "longitude": -70.7},
    )
    assert bearing == pytest.approx(180.0, abs=1e-10)


def test_repeated_calculations_are_deterministic():
    origin = {"latitude": 32.1, "longitude": 34.8}
    destination = {"latitude": 32.3, "longitude": 35.0}
    results = [initial_bearing_deg(origin, destination) for _ in range(10)]
    assert len(set(results)) == 1


def test_helpers_accept_ea317_coordinate_and_direction_constraints():
    origin = GeographicCoordinate(latitude=32.1, longitude=34.8)
    destination = GeographicCoordinate(latitude=32.1, longitude=34.9)
    wind_from = TypeAdapter(DirectionDegrees).validate_python(270.0)

    downwind = downwind_to_direction_deg(wind_from)
    bearing = initial_bearing_deg(origin, destination)
    difference = smallest_angular_difference_deg(bearing, downwind)

    assert TypeAdapter(DirectionDegrees).validate_python(downwind) == 90.0
    assert TypeAdapter(DirectionDegrees).validate_python(bearing) == bearing
    assert bearing == pytest.approx(89.9734300662, abs=1e-10)
    assert isfinite(difference)
    assert 0.0 <= difference <= 180.0
