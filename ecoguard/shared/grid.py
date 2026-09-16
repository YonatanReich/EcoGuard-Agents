"""Deterministic geographic grid primitives for nationwide fire-risk scanning."""

from __future__ import annotations

import math
from dataclasses import dataclass


ISRAEL_RISK_BOUNDS = (34.2, 29.4, 35.9, 33.4)  # west, south, east, north
GRID_RESOLUTION_KM = 5.0
LATITUDE_KM_PER_DEGREE = 110.574
LONGITUDE_KM_PER_DEGREE_AT_EQUATOR = 111.320


@dataclass(frozen=True)
class GridCell:
    cell_id: str
    grid_row: int
    grid_col: int
    latitude: float
    longitude: float


def generate_grid(
    bounds: tuple[float, float, float, float] = ISRAEL_RISK_BOUNDS,
    resolution_km: float = GRID_RESOLUTION_KM,
) -> list[GridCell]:
    """Return stable row-major cell centroids with approximately square spacing."""
    west, south, east, north = bounds
    if not (resolution_km > 0 and west < east and south < north):
        raise ValueError("invalid grid resolution or bounds")

    latitude_step = resolution_km / LATITUDE_KM_PER_DEGREE
    cells: list[GridCell] = []
    row = 0
    while True:
        latitude = south + (row + 0.5) * latitude_step
        if latitude >= north:
            break
        longitude_step = resolution_km / (
            LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * math.cos(math.radians(latitude))
        )
        column = 0
        while True:
            longitude = west + (column + 0.5) * longitude_step
            if longitude >= east:
                break
            cells.append(
                GridCell(
                    cell_id=f"risk-{int(round(resolution_km * 1000)):05d}m-r{row:04d}-c{column:04d}",
                    grid_row=row,
                    grid_col=column,
                    latitude=round(latitude, 8),
                    longitude=round(longitude, 8),
                )
            )
            column += 1
        row += 1
    return cells


def travel_bearing(wind_direction_deg: float) -> float:
    """Where the air is going, from where the wind is coming.

    `wind_direction_10m` is meteorological convention — the bearing the wind
    blows *from*. A northerly at 019 degrees carries smoke toward 199. Getting
    this backwards searches, or burns, the exact half of the map the thing is
    not in.

    It lives here rather than beside either of its callers because both the
    coordinator (which way did the smoke go) and the fire spread model (which
    way does the fire run) need it, they are different stages, and a second
    copy of a conversion whose whole hazard is its sign is how the sign gets
    flipped in one of them.
    """
    return (wind_direction_deg + 180.0) % 360.0
