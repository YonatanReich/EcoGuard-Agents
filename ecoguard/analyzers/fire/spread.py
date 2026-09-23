"""Where a fire that already exists is going, and how fast.

`risk_prediction_agent.py` answers a different question — how likely a fire is
to *start* in a cell. Once one has started that model has nothing further to
say, and there is no trained model here to replace it with: spread supervision
needs labelled perimeter time-series, and Israel produces a handful of fires a
year large enough to have one. A neural spread model fitted on what exists
would be a number that merely looks real.

So this is physics, not statistics. Rothermel's 1972 surface equations give a
rate of spread from the fuel bed, its moisture, the wind and the slope;
Anderson's 1983 length-to-width ratio turns that scalar into the ellipse a
point ignition actually grows into. Both are what FARSITE and BehavePlus run
on, both need no training data, and every constant below is published and
checkable against the Anderson 13 tables.

Two rings come out, not one:

  * **likely** — one ellipse at the forecast wind.
  * **possible** — the union of an ensemble over the wind the forecast might be
    wrong by. Every member contains the ignition point, so every member is
    star-shaped about it, and the union is then exactly the per-bearing maximum
    radius. That is the whole reason this needs no geometry library.

What this does NOT model: suppression, spotting ahead of the front, crown fire
as its own regime, and any barrier finer than the cover grid. The rings are
where an unopposed flaming front can reach. A fire with an engine on it does
not do this, and the report layer has to say so.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from ecoguard.analyzers.fire.fuel_models import (
    SAV_DEAD_10H,
    SAV_DEAD_100H,
    blend,
)
from ecoguard.shared.grid import (
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
    travel_bearing,
)

# --- unit bridges ----------------------------------------------------------
#
# Rothermel is published in English units and every constant in it was fitted
# in those units, so the equations are evaluated there and converted at the
# edges. Restating the constants in SI would be a transcription with nothing
# to check it against.

KG_M2_TO_LB_FT2 = 0.2048161
M_TO_FT = 3.2808399
FT_MIN_TO_M_MIN = 0.3048
KMH_TO_FT_MIN = 54.680665  # 1 km/h = 16.667 m/min = 54.68 ft/min
KMH_TO_MPH = 1.0 / 1.609344

# --- fuel particle constants (Rothermel 1972, as used by BehavePlus) --------

PARTICLE_DENSITY_LB_FT3 = 32.0
HEAT_CONTENT_BTU_LB = 8000.0
TOTAL_MINERAL_CONTENT = 0.0555
EFFECTIVE_MINERAL_CONTENT = 0.010

# Rothermel takes the wind at the flame, not at 10 m, and the gap between the
# two is most of the answer. These are the standard BehavePlus wind adjustment
# factors for an exposed fuel bed and for one under a closed canopy.
#
# ponytail: two constants instead of the Albini-Baughman sheltering
# calculation, which needs canopy height and crown ratio that surface_cells
# does not carry. Replace when the cover grid grows a canopy layer.
WIND_ADJUSTMENT_EXPOSED = 0.40
WIND_ADJUSTMENT_SHELTERED = 0.15
SHELTERED_TREE_COVER = 0.5

# Live fuel moisture, as a fraction of oven-dry weight. Nothing in the
# collection layer measures it — it is a property of the plant, not of the air,
# and it moves over weeks rather than hours. These are the conventional
# Mediterranean-shrub seasonal values, and they matter: live moisture is the
# difference between brush that will not carry fire and brush that carried the
# Carmel fire.
#
# ponytail: a two-value season switch rather than a live fuel moisture model.
# The upgrade path is NDVI, which the collection layer can already reach and
# which tracks curing directly. Until then this is the knob to turn.
LIVE_FUEL_MOISTURE_GREEN = 1.00
LIVE_FUEL_MOISTURE_CURED = 0.60
CURED_SEASON_MONTHS = (6, 7, 8, 9, 10, 11)

# Vertices on a returned ring. 72 is one every five degrees, which at a few
# kilometres is a sub-cell error on the boundary and keeps the ring small
# enough to hand to PostGIS inline.
RING_VERTICES = 72

# What the wind forecast is allowed to be wrong by, for the `possible` union.
# Direction dominates: a 30 degree error swings the head of a 4 km run by
# 2 km, where a 25% speed error moves it by one.
WIND_DIRECTION_ERROR_DEG = 30.0
WIND_SPEED_ERROR_FRACTION = 0.25
ENSEMBLE_DIRECTION_STEPS = (-1.0, -0.5, 0.0, 0.5, 1.0)


def fine_dead_fuel_moisture(temperature_c: float, humidity_percent: float) -> float:
    """Fine dead fuel moisture as a fraction, from what the weather store has.

    Simard's (1968) equilibrium moisture content tables. EMC is what the fuel
    tends toward rather than what it holds at this instant, and it is taken
    here without the solar or shading correction — so this is the exposed,
    daytime reading, which is the conservative one for an active fire.

    This is the most decisive number in the model: above the fuel's moisture of
    extinction the rate of spread is exactly zero, and that threshold is the
    one thing here a forecast can be checked against directly.
    """
    humidity = min(100.0, max(1.0, float(humidity_percent)))
    fahrenheit = float(temperature_c) * 9.0 / 5.0 + 32.0
    if humidity < 10.0:
        emc = 0.03229 + 0.281073 * humidity - 0.000578 * humidity * fahrenheit
    elif humidity < 50.0:
        emc = 2.22749 + 0.160107 * humidity - 0.014784 * fahrenheit
    else:
        emc = (
            21.0606
            + 0.005565 * humidity ** 2
            - 0.00035 * humidity * fahrenheit
            - 0.483199 * humidity
        )
    return max(0.01, emc / 100.0)


def wind_adjustment_factor(cover_fractions: Mapping[str, float]) -> float:
    """How much of the 10 m wind reaches the flame, given what is overhead.

    A closed canopy takes most of it; open grass barely touches it. Exposed as
    its own function because the reduction is applied inside `rate_of_spread`
    and anything comparing this model against a published table — where wind is
    quoted at midflame already — has to undo exactly the same factor. Two
    copies of that rule is how a validation harness ends up confirming a number
    the model never produced.
    """
    sheltered = float(cover_fractions.get("tree_cover", 0.0) or 0.0) >= SHELTERED_TREE_COVER
    return WIND_ADJUSTMENT_SHELTERED if sheltered else WIND_ADJUSTMENT_EXPOSED


def live_moisture_for_month(month: int) -> float:
    """Live fuel moisture from the calendar, which is all we can honestly do.

    Nothing collected measures the water in a living shrub. What is known is
    the Mediterranean growth cycle: green through the wet winter and spring,
    cured from early summer until the first rains. The switch is what makes
    the same hillside refuse to burn in March and run in August.
    """
    return (
        LIVE_FUEL_MOISTURE_CURED
        if int(month) in CURED_SEASON_MONTHS
        else LIVE_FUEL_MOISTURE_GREEN
    )


def _moisture_damping(moisture: float, extinction: float) -> float:
    """Rothermel's damping polynomial: how much the water takes off the fire."""
    if extinction <= 0:
        return 0.0
    ratio = min(1.0, max(0.0, moisture / extinction))
    return max(
        0.0, 1.0 - 2.59 * ratio + 5.11 * ratio ** 2 - 3.52 * ratio ** 3
    )


def rate_of_spread(
    cover_fractions: Mapping[str, float],
    *,
    dead_fuel_moisture: float,
    wind_speed_kmh: float,
    slope_deg: float,
    live_fuel_moisture: float = LIVE_FUEL_MOISTURE_CURED,
) -> dict[str, Any]:
    """Rothermel surface rate of spread for one cell's fuel mixture.

    The two-class form — dead and live weighted separately — rather than one
    lumped fuel bed. That is not a refinement: with everything lumped as dead
    fuel, FM5 brush comes out about five times the published rate, because its
    live two thirds stop being a heat sink and start being fuel. Israeli
    shrubland is FM5.

    Args:
        cover_fractions: WorldCover class shares, as `surface_cells` stores
            them and `fuel_models.blend` consumes them.
        dead_fuel_moisture: fraction, not percent. The fine (1-hour) value;
            the coarser dead classes are offset from it below.
        wind_speed_kmh: wind at 10 m. It is reduced to midflame here rather
            than by the caller, because forgetting that reduction inflates
            spread by more than any other mistake available in this module.
        slope_deg: slope of the ground the fire is standing on.
        live_fuel_moisture: fraction. Defaults to the cured-season value;
            `live_moisture_for_month` picks it from the calendar.

    Returns:
        dict: the head and backing rates in m/min, the wind and slope factors
        that produced them, the effective wind those two combine into, the
        resulting length-to-width ratio, and the blended fuel it ran over.

        Both rates are 0.0 when nothing can carry fire. The two ways that
        happens — no burnable cover, and fuel wetter than its moisture of
        extinction — are different facts about the ground and are reported
        separately in `reason`, because one of them changes within the hour
        and the other does not.
    """
    fuel = blend(cover_fractions)
    stalled = {
        "head_ros_m_per_min": 0.0,
        "back_ros_m_per_min": 0.0,
        "length_to_width": 1.0,
        "effective_wind_kmh": 0.0,
        "wind_factor": 0.0,
        "slope_factor": 0.0,
        "reaction_intensity_btu_ft2_min": 0.0,
        "fuel": fuel,
    }
    if not fuel["burnable_fraction"] or float(fuel["surface_area_to_volume"]) <= 0:
        return {**stalled, "reason": "no_burnable_fuel"}

    moisture = max(0.0, float(dead_fuel_moisture))
    extinction = float(fuel["moisture_of_extinction"])
    if extinction <= 0 or moisture >= extinction:
        return {**stalled, "reason": "fuel_above_moisture_of_extinction"}

    depth = float(fuel["bed_depth_m"]) * M_TO_FT
    if depth <= 0:
        return {**stalled, "reason": "no_burnable_fuel"}

    # The size classes, in English units. Only the 1-hour moisture is measured;
    # the coarser dead classes lag it and sit a couple of points wetter, which
    # is the standard BehavePlus offset when only fine fuel moisture is known.
    dead = [
        (float(fuel["dead_1h_kg_m2"]) * KG_M2_TO_LB_FT2,
         float(fuel["surface_area_to_volume"]) / M_TO_FT, moisture),
        (float(fuel["dead_10h_kg_m2"]) * KG_M2_TO_LB_FT2,
         SAV_DEAD_10H / M_TO_FT, moisture + 0.02),
        (float(fuel["dead_100h_kg_m2"]) * KG_M2_TO_LB_FT2,
         SAV_DEAD_100H / M_TO_FT, moisture + 0.04),
    ]
    live = [
        (float(fuel["live_kg_m2"]) * KG_M2_TO_LB_FT2,
         float(fuel["live_surface_area_to_volume"]) / M_TO_FT,
         max(0.0, float(live_fuel_moisture)))
    ]
    dead = [item for item in dead if item[0] > 0 and item[1] > 0]
    live = [item for item in live if item[0] > 0 and item[1] > 0]
    if not dead:
        return {**stalled, "reason": "no_burnable_fuel"}

    # Weight each class by the surface area it presents, because that is what
    # exchanges heat — not by how much it weighs.
    def _areas(classes):
        return [load * sav / PARTICLE_DENSITY_LB_FT3 for load, sav, _ in classes]

    dead_areas, live_areas = _areas(dead), _areas(live)
    dead_area, live_area = sum(dead_areas), sum(live_areas)
    total_area = dead_area + live_area
    if total_area <= 0:
        return {**stalled, "reason": "no_burnable_fuel"}

    dead_weights = [area / dead_area for area in dead_areas] if dead_area > 0 else []
    live_weights = [area / live_area for area in live_areas] if live_area > 0 else []
    dead_share = dead_area / total_area
    live_share = live_area / total_area

    def _weighted(classes, weights, index):
        return sum(weight * item[index] for weight, item in zip(weights, classes))

    sigma_dead = _weighted(dead, dead_weights, 1)
    sigma_live = _weighted(live, live_weights, 1) if live_weights else 0.0
    sigma = dead_share * sigma_dead + live_share * sigma_live
    if sigma <= 0:
        return {**stalled, "reason": "no_burnable_fuel"}

    dead_moisture = _weighted(dead, dead_weights, 2)
    live_moisture_mean = _weighted(live, live_weights, 2) if live_weights else 0.0
    net_dead = sum(
        weight * load * (1.0 - TOTAL_MINERAL_CONTENT)
        for weight, (load, _, _) in zip(dead_weights, dead)
    )
    net_live = sum(
        weight * load * (1.0 - TOTAL_MINERAL_CONTENT)
        for weight, (load, _, _) in zip(live_weights, live)
    ) if live_weights else 0.0

    # Live fuel has its own extinction moisture, and Rothermel derives it from
    # how much fine dead fuel is there to dry the live fuel out ahead of the
    # front rather than tabulating it. Dry dead fuel raises it; wet dead fuel
    # collapses it, which is why brush will not carry fire on a damp morning
    # however much of it there is.
    if live_weights:
        dead_heating = sum(load * math.exp(-138.0 / sav) for load, sav, _ in dead)
        live_heating = sum(load * math.exp(-500.0 / sav) for load, sav, _ in live)
        if live_heating > 0:
            ratio = dead_heating / live_heating
            live_extinction = max(
                extinction,
                2.9 * ratio * (1.0 - dead_moisture / extinction) - 0.226,
            )
        else:
            live_extinction = extinction
    else:
        live_extinction = extinction

    total_load = sum(load for load, _, _ in dead) + sum(load for load, _, _ in live)
    bulk_density = total_load / depth
    packing = bulk_density / PARTICLE_DENSITY_LB_FT3
    optimum_packing = 3.348 * sigma ** -0.8189
    packing_ratio = packing / optimum_packing

    # Reaction intensity: heat the fuel bed releases per unit area per minute.
    exponent = 133.0 * sigma ** -0.7913
    maximum_velocity = sigma ** 1.5 / (495.0 + 0.0594 * sigma ** 1.5)
    reaction_velocity = (
        maximum_velocity
        * packing_ratio ** exponent
        * math.exp(exponent * (1.0 - packing_ratio))
    )
    mineral_damping = min(1.0, 0.174 * EFFECTIVE_MINERAL_CONTENT ** -0.19)
    reaction_intensity = (
        reaction_velocity
        * HEAT_CONTENT_BTU_LB
        * mineral_damping
        * (
            net_dead * _moisture_damping(dead_moisture, extinction)
            + net_live * _moisture_damping(live_moisture_mean, live_extinction)
        )
    )
    if reaction_intensity <= 0:
        return {**stalled, "reason": "fuel_above_moisture_of_extinction"}

    # Heat sink: what it costs to bring the next fuel up to ignition. Weighted
    # the same way, so wet live fuel raises the cost instead of vanishing.
    def _sink(classes, weights):
        return sum(
            weight * math.exp(-138.0 / sav) * (250.0 + 1116.0 * class_moisture)
            for weight, (_, sav, class_moisture) in zip(weights, classes)
        )

    heating = dead_share * _sink(dead, dead_weights)
    if live_weights:
        heating += live_share * _sink(live, live_weights)
    heat_sink = bulk_density * heating
    if heat_sink <= 0:
        return {**stalled, "reason": "no_burnable_fuel"}

    propagating_flux = math.exp(
        (0.792 + 0.681 * math.sqrt(sigma)) * (packing + 0.1)
    ) / (192.0 + 0.2595 * sigma)

    no_wind_ros = reaction_intensity * propagating_flux / heat_sink  # ft/min

    # Wind and slope enter as multipliers on that.
    adjustment = wind_adjustment_factor(cover_fractions)
    midflame_ft_min = max(0.0, float(wind_speed_kmh)) * KMH_TO_FT_MIN * adjustment

    wind_c = 7.47 * math.exp(-0.133 * sigma ** 0.55)
    wind_b = 0.02526 * sigma ** 0.54
    wind_e = 0.715 * math.exp(-3.59e-4 * sigma)
    wind_factor = wind_c * midflame_ft_min ** wind_b * packing_ratio ** -wind_e
    slope_factor = (
        5.275 * packing ** -0.3 * math.tan(math.radians(max(0.0, float(slope_deg)))) ** 2
    )

    head = no_wind_ros * (1.0 + wind_factor + slope_factor) * float(fuel["spread_adjustment"])

    # The wind that would produce the combined wind-plus-slope push on its own.
    # It is what sets the shape of the ellipse, so a fire running uphill in
    # still air comes out elongated rather than drawn as a circle.
    combined = wind_factor + slope_factor
    if combined > 0 and wind_b > 0:
        effective_ft_min = (combined / (wind_c * packing_ratio ** -wind_e)) ** (1.0 / wind_b)
    else:
        effective_ft_min = 0.0
    effective_kmh = effective_ft_min / KMH_TO_FT_MIN

    # Anderson (1983): the ellipse lengthens with the wind. Capped at 8 because
    # the relation was fitted over open-country winds and a needle-thin fire is
    # not what a 100 km/h gust produces, it is what extrapolation produces.
    length_to_width = min(8.0, 1.0 + 0.25 * effective_kmh * KMH_TO_MPH)
    eccentric = math.sqrt(max(0.0, length_to_width ** 2 - 1.0))
    back = head * (length_to_width - eccentric) / (length_to_width + eccentric)

    return {
        "head_ros_m_per_min": head * FT_MIN_TO_M_MIN,
        "back_ros_m_per_min": back * FT_MIN_TO_M_MIN,
        "length_to_width": length_to_width,
        "effective_wind_kmh": effective_kmh,
        "wind_factor": wind_factor,
        "slope_factor": slope_factor,
        "reaction_intensity_btu_ft2_min": reaction_intensity,
        "fuel": fuel,
        "reason": None,
    }


def spread_heading(
    wind_direction_deg: float,
    wind_factor: float,
    aspect_deg: float | None,
    slope_factor: float,
) -> float:
    """Which way the head of the fire runs: wind and slope added as vectors.

    `wind_direction_deg` is meteorological — the bearing the wind blows *from* —
    so it goes through `travel_bearing` first. Getting that backwards points
    the fire at exactly the towns that are safe. `aspect_deg` is the direction
    the ground faces, which is downhill; fire runs up, so the slope vector
    points the opposite way.

    Weighting each term by its own Rothermel factor is what lets a steep slope
    beat a light wind and a strong wind beat a gentle slope, without inventing
    a second set of tuning constants to arbitrate between them.
    """
    carried = math.radians(travel_bearing(float(wind_direction_deg)))
    east = wind_factor * math.sin(carried)
    north = wind_factor * math.cos(carried)
    if aspect_deg is not None and slope_factor > 0:
        upslope = math.radians((float(aspect_deg) + 180.0) % 360.0)
        east += slope_factor * math.sin(upslope)
        north += slope_factor * math.cos(upslope)
    if east == 0.0 and north == 0.0:
        return travel_bearing(float(wind_direction_deg))
    return math.degrees(math.atan2(east, north)) % 360.0


def ellipse_radius_m(
    bearing_deg: float,
    heading_deg: float,
    head_m: float,
    back_m: float,
    length_to_width: float,
) -> float:
    """Distance from the ignition point to the ellipse edge, on one bearing.

    The ignition point is not the centre of the ellipse and treating it as one
    is the standard way to get this wrong: it sits `back_m` from the rear
    vertex, so the centre lies `(head_m - back_m) / 2` ahead of it along the
    heading. This solves the ellipse equation written about the ignition point
    instead, which is also what makes every member of the ensemble star-shaped
    about a single shared origin and the union a per-bearing maximum.
    """
    length = head_m + back_m
    if length <= 0:
        return 0.0
    semi_major = length / 2.0
    semi_minor = semi_major / max(1.0, float(length_to_width))
    offset = (head_m - back_m) / 2.0

    angle = math.radians(float(bearing_deg) - float(heading_deg))
    cosine, sine = math.cos(angle), math.sin(angle)
    a = cosine ** 2 / semi_major ** 2 + sine ** 2 / semi_minor ** 2
    b = -2.0 * offset * cosine / semi_major ** 2
    c = offset ** 2 / semi_major ** 2 - 1.0
    discriminant = b * b - 4.0 * a * c
    if a <= 0 or discriminant < 0:
        return 0.0
    return max(0.0, (-b + math.sqrt(discriminant)) / (2.0 * a))


def offset_point(
    latitude: float, longitude: float, bearing_deg: float, distance_m: float
) -> tuple[float, float]:
    """A point at a bearing and distance, on the local flat plane.

    Flat rather than geodesic on purpose: over the few kilometres a fire covers
    in a shift, the difference is centimetres, and the same approximation is
    already what `packaging.distance_km` measures incidents with.
    """
    km = distance_m / 1000.0
    angle = math.radians(float(bearing_deg))
    scale = math.cos(math.radians(float(latitude)))
    north_km = km * math.cos(angle)
    east_km = km * math.sin(angle)
    return (
        float(latitude) + north_km / LATITUDE_KM_PER_DEGREE,
        float(longitude)
        + east_km / (LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * max(1e-9, scale)),
    )


def spread_rings(
    latitude: float,
    longitude: float,
    behaviour: Mapping[str, Any],
    *,
    wind_direction_deg: float,
    aspect_deg: float | None,
    horizon_minutes: float,
) -> dict[str, Any]:
    """The `likely` and `possible` rings for one fire, after `horizon_minutes`.

    `behaviour` is a `rate_of_spread` result. Returns GeoJSON-order rings —
    [longitude, latitude] pairs, first vertex repeated last — so a ring can be
    handed straight to `ST_GeomFromGeoJSON` and reuse every polygon query the
    store already has.

    A stalled fire returns empty rings and a `reason`, never a degenerate
    polygon. A zero-area ring passed downstream reads as "nothing is at risk",
    which is the same output a genuinely contained fire produces and must stay
    distinguishable from it.
    """
    head_ros = float(behaviour.get("head_ros_m_per_min") or 0.0)
    if head_ros <= 0:
        return {
            "status": "stalled",
            "reason": behaviour.get("reason") or "no_spread",
            "likely": [],
            "possible": [],
            "heading_deg": None,
            "head_distance_m": 0.0,
            "radii_m": {},
        }

    back_ros = float(behaviour.get("back_ros_m_per_min") or 0.0)
    length_to_width = float(behaviour.get("length_to_width") or 1.0)
    wind_factor = float(behaviour.get("wind_factor") or 0.0)
    slope_factor = float(behaviour.get("slope_factor") or 0.0)
    minutes = max(0.0, float(horizon_minutes))

    heading = spread_heading(wind_direction_deg, wind_factor, aspect_deg, slope_factor)
    head_m = head_ros * minutes
    back_m = back_ros * minutes

    bearings = [i * 360.0 / RING_VERTICES for i in range(RING_VERTICES)]
    likely = {b: ellipse_radius_m(b, heading, head_m, back_m, length_to_width) for b in bearings}

    # The ensemble. Speed error scales both rates, so it is applied to the
    # distances; direction error swings the heading. The union is the
    # per-bearing maximum, which is exact here because every member contains
    # the ignition point.
    possible = dict(likely)
    fast_head = head_m * (1.0 + WIND_SPEED_ERROR_FRACTION)
    fast_back = back_m * (1.0 + WIND_SPEED_ERROR_FRACTION)
    for step in ENSEMBLE_DIRECTION_STEPS:
        member_heading = (heading + step * WIND_DIRECTION_ERROR_DEG) % 360.0
        for bearing in bearings:
            radius = ellipse_radius_m(
                bearing, member_heading, fast_head, fast_back, length_to_width
            )
            if radius > possible[bearing]:
                possible[bearing] = radius

    return {
        "status": "ok",
        "reason": None,
        "heading_deg": round(heading, 1),
        "head_distance_m": round(head_m, 1),
        "horizon_minutes": minutes,
        "likely": _ring(latitude, longitude, likely),
        "possible": _ring(latitude, longitude, possible),
        "radii_m": {
            "likely": {round(b, 1): round(r, 1) for b, r in likely.items()},
            "possible": {round(b, 1): round(r, 1) for b, r in possible.items()},
        },
    }


def _ring(
    latitude: float, longitude: float, radii: Mapping[float, float]
) -> list[list[float]]:
    """A closed GeoJSON ring from per-bearing radii about one origin."""
    ring = []
    for bearing in sorted(radii):
        point_lat, point_lon = offset_point(latitude, longitude, bearing, radii[bearing])
        ring.append([round(point_lon, 6), round(point_lat, 6)])
    if ring:
        ring.append(list(ring[0]))
    return ring
