"""Small geographic calculations shared by resource-allocation services."""

from __future__ import annotations

import math


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
