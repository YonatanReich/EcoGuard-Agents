"""Small geographic calculations shared by resource-allocation services."""

from __future__ import annotations

import math


def coordinates(location):
    """Validate a location and return its latitude and longitude."""
    if not isinstance(location, dict):
        raise ValueError("location must be an object")

    latitude = location.get("latitude")
    longitude = location.get("longitude")
    for value in (latitude, longitude):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError("location must contain valid coordinates")

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("coordinates are outside their valid ranges")

    return float(latitude), float(longitude)


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two coordinates in kilometers."""
    lon1, lat1, lon2, lat2 = map(
        math.radians,
        (lon1, lat1, lon2, lat2),
    )
    longitude_delta = lon2 - lon1
    latitude_delta = lat2 - lat1
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(value))
