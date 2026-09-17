"""Joining incidents that are one thing happening, not two things nearby.

Requirement 3: a fire and the air pollution it causes are a hybrid event, not a
fire plus a mystery pollution episode.

This is a different relation from the one in `matching.py`. Matching asks
*identity* — is this the same event? — and requires the same hazard. This asks
*causation*: did that cause this? Different hazards by definition, and the two
must not be confused, because merging on mere proximity would fold a refinery's
routine emissions into every nearby fire.

**Smoke does not stay put.** The pollution a fire causes is not in the fire's
cell; it is wherever the wind put it, which for a 15 km/h wind over two hours is
thirty kilometres away. A plain radius would reach that plume and would equally
reach the refinery sitting the same distance *upwind* — a source that cannot
possibly be the fire's doing. So the search is a downwind cone, built from the
wind this system already records hourly for every cell.

The bearing conversion is the trap. `wind_direction_10m` is meteorological: the
direction the wind blows **from**. Smoke travels toward the opposite bearing,
and getting that backwards searches precisely the half of the map where the
plume cannot be.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ecoguard.database.repositories.weather_history import hourly_for_cell
from ecoguard.shared.cells import cell_by_id, service_area_cells
from ecoguard.shared.grid import (
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
    travel_bearing,
)
from ecoguard.shared.signals import AIR_QUALITY, FIRE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CausalRule:
    """How far and how long an effect may be from its cause, and which way."""

    max_km: float
    max_lag: timedelta
    # Whether the effect is carried by wind. False means look in every
    # direction — flooding spreads downhill, not downwind.
    downwind: bool
    # Half-angle of the search cone. Wide because a plume meanders and the
    # wind we have is an hourly average at one point, not a trajectory.
    half_angle_deg: float = 45.0


# Deliberately sparse. Every entry is a claim that one hazard physically
# produces another, and a wrong entry silently swallows a genuinely separate
# incident into an unrelated one — the failure mode nobody notices, because the
# result is one plausible incident rather than two.
CAUSAL_RULES: dict[tuple[str, str], CausalRule] = {
    (FIRE, AIR_QUALITY): CausalRule(
        max_km=25.0, max_lag=timedelta(hours=6), downwind=True
    ),
}


def bearing_between(
    from_latitude: float, from_longitude: float,
    to_latitude: float, to_longitude: float,
) -> float:
    """Compass bearing from one point to another, degrees clockwise from north."""
    scale = math.cos(math.radians((from_latitude + to_latitude) / 2))
    east = (to_longitude - from_longitude) * LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * scale
    north = (to_latitude - from_latitude) * LATITUDE_KM_PER_DEGREE
    return round(math.degrees(math.atan2(east, north)), 6) % 360.0


def distance_km(
    from_latitude: float, from_longitude: float,
    to_latitude: float, to_longitude: float,
) -> float:
    """Ground distance between two points, good enough at Israel's scale."""
    scale = math.cos(math.radians((from_latitude + to_latitude) / 2))
    return math.hypot(
        (to_latitude - from_latitude) * LATITUDE_KM_PER_DEGREE,
        (to_longitude - from_longitude) * LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * scale,
    )


def angular_gap(first: float, second: float) -> float:
    """Smallest angle between two bearings, 0-180.

    Written out rather than subtracted because bearings wrap: 350 and 10 are
    twenty degrees apart, and plain subtraction calls it three hundred and forty.
    """
    return abs((first - second + 180.0) % 360.0 - 180.0)


def wind_direction_at(cell_id: str, at: datetime) -> float | None:
    """The most recent stored wind direction for a cell, or None.

    Looks back a few hours rather than demanding the exact hour: the cause and
    the effect are hours apart by construction, and a single missing hour in
    the weather series should not silently disable causal linking.
    """
    series = hourly_for_cell(cell_id, at - timedelta(hours=6), at)
    hourly = series.get("hourly") or {}
    directions = hourly.get("wind_direction_10m") or []
    for value in reversed(directions):
        if value is not None:
            return float(value)
    return None


def downwind_cells(
    cell_id: str, at: datetime, rule: CausalRule
) -> tuple[tuple[str, float, float], ...]:
    """Cells the wind would carry something into: (cell_id, km, bearing).

    Returns empty when the wind is unknown. That is deliberate and is the
    conservative direction to fail: with no wind we cannot say which side of
    the fire the smoke is on, and linking every nearby pollution reading
    "just in case" is exactly the false merge this module exists to avoid.
    """
    origin = cell_by_id(cell_id)
    if origin is None:
        return ()

    direction = wind_direction_at(cell_id, at)
    if direction is None:
        logger.info("packaging: no wind for %s, skipping downwind link", cell_id)
        return ()
    carried_toward = travel_bearing(direction)

    downwind = []
    for candidate in service_area_cells():
        if candidate.cell_id == cell_id:
            continue
        km = distance_km(
            origin.latitude, origin.longitude, candidate.latitude, candidate.longitude
        )
        if km > rule.max_km:
            continue
        bearing = bearing_between(
            origin.latitude, origin.longitude, candidate.latitude, candidate.longitude
        )
        if angular_gap(bearing, carried_toward) <= rule.half_angle_deg:
            downwind.append((candidate.cell_id, round(km, 2), round(bearing, 1)))
    return tuple(downwind)


def causal_link(
    cause: dict[str, Any], effect: dict[str, Any]
) -> dict[str, Any] | None:
    """Whether `effect` was plausibly caused by `cause`, and the reasoning.

    Args:
        cause: an open incident that might be producing something.
        effect: an open incident that might be the product.

    Returns:
        A link record naming the rule, distance, bearing and lag — or None.
        The rationale travels with the link so a merged hybrid can explain
        itself: "air_quality joined to fire: 12.4 km downwind on bearing 199".
        A merge nobody can account for is one nobody can correct.
    """
    for cause_hazard in cause.get("hazards") or ():
        for effect_hazard in effect.get("hazards") or ():
            rule = CAUSAL_RULES.get((cause_hazard, effect_hazard))
            if rule is None:
                continue

            # The effect cannot precede its cause, and must not trail it by
            # more than the rule allows.
            lag = effect["last_signal_at"] - cause["first_seen_at"]
            if lag < timedelta(0) or lag > rule.max_lag:
                continue

            if not rule.downwind:
                continue

            reachable = {
                cell: (km, bearing)
                for cell, km, bearing in downwind_cells(
                    cause["cells"][0], cause["first_seen_at"], rule
                )
            }
            for cell in effect.get("cells") or ():
                if cell in reachable:
                    km, bearing = reachable[cell]
                    return {
                        "cause_hazard": cause_hazard,
                        "effect_hazard": effect_hazard,
                        "cause_incident": cause["id"],
                        "distance_km": km,
                        "bearing_deg": bearing,
                        "lag_hours": round(lag.total_seconds() / 3600, 2),
                        "rationale": (
                            f"{effect_hazard} joined to {cause_hazard}: "
                            f"{km} km downwind on bearing {bearing:.0f}"
                        ),
                    }
    return None
