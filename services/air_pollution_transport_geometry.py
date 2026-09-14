"""Pure geometry helpers for pollution transport screening.

Coordinates use WGS84 latitude/longitude values, while the initial bearing is
calculated on a spherical Earth.  That standard great-circle approximation is
appropriate for settlement-scale directional screening; it is not an
ellipsoidal survey calculation or evidence of pollution transport/exposure.
"""

from __future__ import annotations

from math import asin, atan2, cos, degrees, isclose, isfinite, radians, sin, sqrt
from numbers import Real
from typing import Mapping, TypeAlias

from agents.air_pollution_anomaly_schemas import GeographicCoordinate


CoordinateInput: TypeAlias = GeographicCoordinate | Mapping[str, object]
MEAN_EARTH_RADIUS_M = 6_371_008.8


class UndefinedBearingError(ValueError):
    """Raised when two points do not define a unique initial bearing."""


def _validated_direction(value: float, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite number")
    normalized_value = float(value)
    if not isfinite(normalized_value):
        raise ValueError(f"{field_name} must be a finite number")
    if not 0.0 <= normalized_value < 360.0:
        raise ValueError(f"{field_name} must satisfy 0 <= degrees < 360")
    return normalized_value


def _validated_coordinate(value: CoordinateInput) -> GeographicCoordinate:
    payload = value.model_dump() if isinstance(value, GeographicCoordinate) else value
    return GeographicCoordinate.model_validate(payload)


def downwind_to_direction_deg(wind_from_direction_deg: float) -> float:
    """Convert meteorological wind-from direction to downwind-to direction."""

    wind_from = _validated_direction(
        wind_from_direction_deg,
        field_name="wind_from_direction_deg",
    )
    return (wind_from + 180.0) % 360.0


def geodesic_distance_m(
    origin: CoordinateInput,
    destination: CoordinateInput,
) -> float:
    """Return spherical great-circle distance in metres using Haversine.

    Inputs retain WGS84 latitude/longitude semantics. The IUGG mean Earth
    radius provides a deterministic screening distance, not survey precision.
    """

    origin_point = _validated_coordinate(origin)
    destination_point = _validated_coordinate(destination)
    latitude_1 = radians(origin_point.latitude)
    latitude_2 = radians(destination_point.latitude)
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = radians(
        ((destination_point.longitude - origin_point.longitude + 180.0) % 360.0)
        - 180.0
    )
    haversine = (
        sin(latitude_delta / 2.0) ** 2
        + cos(latitude_1) * cos(latitude_2) * sin(longitude_delta / 2.0) ** 2
    )
    bounded_haversine = min(1.0, max(0.0, haversine))
    return 2.0 * MEAN_EARTH_RADIUS_M * asin(sqrt(bounded_haversine))


def initial_bearing_deg(
    origin: CoordinateInput,
    destination: CoordinateInput,
) -> float:
    """Return initial great-circle bearing from ``origin`` to ``destination``.

    Bearings are degrees clockwise from true north in ``[0, 360)``. Coincident
    and antipodal points have no unique initial bearing and raise
    :class:`UndefinedBearingError`.
    """

    origin_point = _validated_coordinate(origin)
    destination_point = _validated_coordinate(destination)
    if origin_point == destination_point:
        raise UndefinedBearingError("identical coordinates do not define a bearing")

    latitude_1 = radians(origin_point.latitude)
    latitude_2 = radians(destination_point.latitude)
    longitude_delta_deg = (
        (destination_point.longitude - origin_point.longitude + 180.0) % 360.0
    ) - 180.0
    longitude_delta = radians(longitude_delta_deg)

    x = sin(longitude_delta) * cos(latitude_2)
    y = (
        cos(latitude_1) * sin(latitude_2)
        - sin(latitude_1) * cos(latitude_2) * cos(longitude_delta)
    )
    if isclose(x, 0.0, abs_tol=1e-15) and isclose(y, 0.0, abs_tol=1e-15):
        raise UndefinedBearingError("coordinates do not define a unique initial bearing")

    return (degrees(atan2(x, y)) + 360.0) % 360.0


def smallest_angular_difference_deg(
    settlement_bearing_deg: float,
    downwind_to_direction_deg: float,
) -> float:
    """Return the unsigned shortest separation of two directions in degrees."""

    settlement_bearing = _validated_direction(
        settlement_bearing_deg,
        field_name="settlement_bearing_deg",
    )
    downwind_direction = _validated_direction(
        downwind_to_direction_deg,
        field_name="downwind_to_direction_deg",
    )
    return abs((settlement_bearing - downwind_direction + 180.0) % 360.0 - 180.0)
