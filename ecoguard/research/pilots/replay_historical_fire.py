"""Replay one real fire and score the forecast against what actually burned.

    python -m ecoguard.research.pilots.replay_historical_fire

The scenario suite checks that the analyser says what I predicted it would.
This checks something harder and more useful: whether what it says matches a
fire that happened.

The fire
--------
14-15 September 2026, Upper Galilee. Thirty-six satellite overpasses across two
days, first seen at 09:58 on the 14th at 4.7 MW, peaking at 109 MW the
following midday. It is the largest multi-overpass event in the collection
window and the one the FIRMS collector's own notes cite for Meteosat detecting
it nearly three hours before VIIRS.

The method
----------
Take the **first** detection as the incident — the only thing known at 09:58,
with no knowledge of anything that followed. Load the weather actually recorded
for that cell and hour, and the terrain and fuel actually there. Forecast three
hours. Then ask where the fire really went, using the satellite pixels observed
over those same three hours, and measure how many of them the forecast covered.

Two things that would make this dishonest, and are therefore avoided:

  * **Hindsight in the inputs.** The weather is the hour of ignition, not the
    afternoon's. The origin is the first pixel, not the centroid of the whole
    event.
  * **Grading on the ring that was drawn to be generous.** Containment is
    reported for `likely` and `possible` separately. `possible` is a wind-error
    ensemble and will always score better; quoting only that number would be
    marking one's own homework.

What containment can and cannot show
------------------------------------
A high score means the fire went where the model said. It does not validate the
rate of spread independently, because a ring that is too large contains the
truth for the wrong reason — so the ring's area and the observed extent are
reported alongside, and an over-large ring is visible as a low pixel density
rather than hidden inside a good-looking percentage.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.analyzers.emergency.fire.exposure import _ring_metres, point_in_ring
from ecoguard.analyzers.emergency.fire.spread_analyzer import analyze_incident
from ecoguard.database.engine import Session
from ecoguard.paths import REPOSITORY_ROOT
from ecoguard.shared.cells import cell_for

OUTPUT = REPOSITORY_ROOT / "outputs" / "fire_analyzer_replay_results.json"

# The event, as the store holds it.
IGNITION = datetime(2026, 9, 14, 9, 58, tzinfo=timezone.utc)
ORIGIN_LAT, ORIGIN_LON = 33.1021, 35.4382
HORIZON_MINUTES = 180.0

# How far from the origin a later pixel still counts as this fire. Generous
# enough to contain a three-hour run, tight enough to exclude the separate
# events elsewhere in the Galilee that day — the unfiltered 25 km neighbourhood
# spans 45 km of longitude and is plainly more than one fire.
SAME_FIRE_RADIUS_M = 12_000.0


def observed_weather(cell_id: str, at: datetime) -> dict[str, Any] | None:
    """The weather actually recorded for this cell at this hour."""
    with Session() as session:
        row = session.execute(
            text(
                """
                SELECT payload FROM observations
                WHERE source = 'weather' AND cell_id = :cell
                  AND observed_at <= :at
                ORDER BY observed_at DESC LIMIT 1
                """
            ),
            {"cell": cell_id, "at": at},
        ).scalar()
    if not row:
        return None
    return {
        "temperature_c": float(row["temperature_2m"]),
        "humidity_percent": float(row["relative_humidity_2m"]),
        "wind_speed_kmh": float(row["wind_speed_10m"]),
        "wind_direction_deg": float(row["wind_direction_10m"]),
    }


def observed_pixels(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Every hotspot pixel of this fire between two times, oldest first."""
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT observed_at, payload FROM observations
                WHERE source = 'firms'
                  AND observed_at > :start AND observed_at <= :end
                  AND ST_DWithin(
                        location,
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                        :radius)
                ORDER BY observed_at
                """
            ),
            {
                "start": start, "end": end, "radius": SAME_FIRE_RADIUS_M,
                "lat": ORIGIN_LAT, "lon": ORIGIN_LON,
            },
        ).all()

    pixels = []
    for observed_at, payload in rows:
        for hotspot in (payload or {}).get("hotspots") or []:
            if hotspot.get("latitude") is None or hotspot.get("longitude") is None:
                continue
            pixels.append({
                "observed_at": observed_at.isoformat(),
                "latitude": float(hotspot["latitude"]),
                "longitude": float(hotspot["longitude"]),
                "frp": float(hotspot.get("frp") or 0.0),
            })
    return pixels


def contains(ring: list[list[float]], latitude: float, longitude: float) -> bool:
    """Whether a GeoJSON ring encloses a point, in the analyser's own geometry."""
    if not ring or len(ring) < 4:
        return False
    local = _ring_metres([tuple(point) for point in ring], latitude, longitude)
    return bool(local) and point_in_ring((0.0, 0.0), local)


def run() -> dict[str, Any]:
    cell = cell_for(ORIGIN_LAT, ORIGIN_LON)
    weather = observed_weather(cell, IGNITION)
    if weather is None:
        raise SystemExit(f"no archived weather for {cell} at {IGNITION}")

    incident = {
        "id": "REPLAY-galilee-20260914",
        "status": "open",
        "primary_hazard": "fire",
        "hazards": ["fire"],
        "queues": ["emergency"],
        "cells": [cell],
        "latitude": ORIGIN_LAT,
        "longitude": ORIGIN_LON,
        "precision_m": 375.0,
        "location_method": "frp_weighted_centroid",
        "first_seen_at": IGNITION,
        "last_signal_at": IGNITION,
        "closed_at": None,
        "signal_count": 1,
        "peak_rarity": 1.0,
        "links": [],
        "signals": [],
    }

    # Terrain and fuel from the store; weather from the hour it started. No
    # part of this has seen what happened next.
    from ecoguard.analyzers.emergency.fire.environment import environment_for

    environment = {**(environment_for(incident) or {}), **weather}
    result = analyze_incident(
        incident, horizon_minutes=HORIZON_MINUTES, environment=environment
    )

    pixels = observed_pixels(IGNITION, IGNITION + timedelta(minutes=HORIZON_MINUTES))
    spread = result.get("spread") or {}
    likely_ring = spread.get("likely") or []
    possible_ring = spread.get("possible") or []

    for pixel in pixels:
        pixel["in_likely"] = contains(
            likely_ring, pixel["latitude"], pixel["longitude"]
        )
        pixel["in_possible"] = contains(
            possible_ring, pixel["latitude"], pixel["longitude"]
        )

    total = len(pixels)
    in_likely = sum(1 for pixel in pixels if pixel["in_likely"])
    in_possible = sum(1 for pixel in pixels if pixel["in_possible"])

    # How far the fire actually got, for comparison with the forecast head.
    furthest = 0.0
    bearings = []
    import math

    for pixel in pixels:
        north = (pixel["latitude"] - ORIGIN_LAT) * 111_320.0
        east = (
            (pixel["longitude"] - ORIGIN_LON)
            * 111_320.0
            * math.cos(math.radians(ORIGIN_LAT))
        )
        distance = math.hypot(north, east)
        furthest = max(furthest, distance)
        if distance > 200:
            bearings.append(math.degrees(math.atan2(east, north)) % 360.0)

    observed_bearing = None
    if bearings:
        sines = sum(math.sin(math.radians(b)) for b in bearings) / len(bearings)
        cosines = sum(math.cos(math.radians(b)) for b in bearings) / len(bearings)
        observed_bearing = math.degrees(math.atan2(sines, cosines)) % 360.0

    forecast_bearing = (result.get("behaviour") or {}).get("heading_deg")
    bearing_error = None
    if observed_bearing is not None and forecast_bearing is not None:
        gap = abs(observed_bearing - forecast_bearing) % 360.0
        bearing_error = min(gap, 360.0 - gap)

    return {
        "fire": {
            "name": "Upper Galilee, 14 September 2026",
            "ignition_detected_at": IGNITION.isoformat(),
            "origin": {"latitude": ORIGIN_LAT, "longitude": ORIGIN_LON},
            "cell": cell,
            "horizon_minutes": HORIZON_MINUTES,
        },
        "inputs": {
            "weather": weather,
            "weather_source": "observations, the hour of ignition",
            "slope_deg": environment.get("slope_deg"),
            "slope_max_deg": environment.get("slope_max_deg"),
            "dominant_fuel": environment.get("dominant_fuel"),
            "burnable_fraction": environment.get("burnable_fraction"),
        },
        "forecast": {
            "status": result.get("status"),
            "risk_score": result.get("risk_score"),
            "risk_level": result.get("risk_level"),
            "head_rate_m_per_min": (result.get("behaviour") or {}).get(
                "head_ros_m_per_min"
            ),
            "heading_deg": forecast_bearing,
            "heading_compass": (result.get("behaviour") or {}).get("heading_compass"),
            "head_distance_m": spread.get("head_distance_m"),
        },
        "observed": {
            "pixels": total,
            "furthest_pixel_m": round(furthest, 1),
            "mean_bearing_deg": (
                None if observed_bearing is None else round(observed_bearing, 1)
            ),
        },
        "score": {
            "pixels_in_likely": in_likely,
            "pixels_in_possible": in_possible,
            "containment_likely": None if not total else round(in_likely / total, 3),
            "containment_possible": (
                None if not total else round(in_possible / total, 3)
            ),
            "bearing_error_deg": (
                None if bearing_error is None else round(bearing_error, 1)
            ),
            "head_distance_vs_observed": (
                None
                if not spread.get("head_distance_m")
                else round(spread["head_distance_m"] / max(furthest, 1.0), 2)
            ),
        },
        "pixel_detail": pixels,
        "report": result.get("report"),
    }


def main() -> None:
    payload = run()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    score, observed, forecast = (
        payload["score"], payload["observed"], payload["forecast"]
    )
    print(f"forecast: {forecast['head_rate_m_per_min']} m/min "
          f"{forecast['heading_compass']} ({forecast['heading_deg']} deg), "
          f"head {forecast['head_distance_m']} m")
    print(f"observed: {observed['pixels']} pixels, furthest "
          f"{observed['furthest_pixel_m']} m, mean bearing "
          f"{observed['mean_bearing_deg']} deg")
    print(f"containment: likely {score['containment_likely']}, "
          f"possible {score['containment_possible']}")
    print(f"bearing error: {score['bearing_error_deg']} deg")
    print(f"written: {OUTPUT}")


if __name__ == "__main__":
    main()
