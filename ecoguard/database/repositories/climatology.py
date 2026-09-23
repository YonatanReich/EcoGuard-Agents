"""Is this reading unusual for here, at this time of year?

The comparison a rolling window cannot make. A window only says whether an hour
differs from the week behind it, and that week drifts with whatever is
happening: a heatwave that builds over six days never looks unusual on any one
of them. Those slow, persistent conditions are exactly what fire cares about.

A seasonal baseline does not drift. September is compared against every
September on record, not against itself.

Spread is measured in a way that survives a variable like rainfall, where most
hours are zero and the average describes an hour that never happened; where
even that fails, the answer falls back to rank - "higher than 95% of hours
here" is a fact that stays true regardless of the shape of the data."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.shared.grid import (
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
)

# Iglewicz and Hoaglin's threshold for the modified z-score. Deliberately less
# twitchy than the 2-sigma a mean-based score would flag: at 3.5 an alert means
# the reading sits outside anything the last decade produced in this bucket,
# which is the claim worth waking someone for.
ANOMALY_Z = 3.5

# 0.6745 is the 75th percentile of the standard normal, and it rescales MAD so
# a modified z-score is comparable to an ordinary one on normal-ish data.
MAD_SCALE = 0.6745

# How far a cell may sit from its baseline and still be represented by it.
# Baselines are built on a ~15 km grid, so a complete set puts every cell within
# roughly 11 km of one. 25 km is comfortably beyond that and still far short of
# the distance at which Israel's climates stop resembling each other — the
# coastal plain and the Jordan rift are 40 km apart and share almost nothing.
MAX_BASELINE_DISTANCE_KM = 25.0


def _band(value: float, bucket: dict[str, Any]) -> str:
    """Which fifth of the distribution a value falls in.

    The comparisons are asymmetric on purpose. A value *equal* to a percentile
    belongs to the band below it — sitting exactly at p95 is the top of "high",
    not the bottom of "extremely_high" — and that is what keeps a degenerate
    bucket sane.

    Degenerate is the normal case for precipitation: it does not rain in most
    hours, so p05 through p95 are all 0.0. Under strict-below comparisons a dry
    hour matches no band and falls through to the last one, which would report
    every rainless hour in the country as extreme rainfall. Ties resolving
    downward put it in "typical", where it belongs.
    """
    if value < bucket["p05"]:
        return "extremely_low"
    if value < bucket["p25"]:
        return "low"
    if value <= bucket["p75"]:
        return "typical"
    if value <= bucket["p95"]:
        return "high"
    return "extremely_high"


@lru_cache(maxsize=1)
def _baseline_cells() -> tuple[tuple[str, float, float], ...]:
    """Which cells actually have baselines, with their coordinates."""
    with Session() as session:
        ids = set(
            session.execute(
                text("SELECT DISTINCT cell_id FROM weather_baselines")
            ).scalars().all()
        )
    from ecoguard.shared.cells import service_area_cells

    return tuple(
        (cell.cell_id, cell.latitude, cell.longitude)
        for cell in service_area_cells()
        if cell.cell_id in ids
    )


def baseline_cell_for(latitude: float, longitude: float) -> str | None:
    """The nearest cell that has a baseline, or None if none is near enough.

    Longitude is scaled by cos(latitude) so "nearest" is nearest on the ground
    rather than in degrees — at 31 N a degree of longitude is 15% shorter than
    a degree of latitude, and ignoring that skews the choice eastward.

    The distance ceiling is the important part. "Nearest" is meaningless when
    the nearest is 200 km away: a half-built baseline set once mapped the
    Galilee onto a Negev cell and returned desert percentiles for a Mediterranean
    climate, with every field looking perfectly well-formed. Returning None
    there is the only honest answer — a missing baseline must not be able to
    masquerade as a confident one.
    """
    candidates = _baseline_cells()
    if not candidates:
        return None

    scale = math.cos(math.radians(latitude))
    cell_id, cell_latitude, cell_longitude = min(
        candidates,
        key=lambda c: (c[1] - latitude) ** 2 + ((c[2] - longitude) * scale) ** 2,
    )
    distance = math.hypot(
        (cell_latitude - latitude) * LATITUDE_KM_PER_DEGREE,
        (cell_longitude - longitude) * LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * scale,
    )
    return cell_id if distance <= MAX_BASELINE_DISTANCE_KM else None


def assess(value: float, bucket: dict[str, Any]) -> dict[str, Any]:
    """Compare one reading against one bucket.

    Returns the verdict plus the numbers behind it, so a caller can show its
    working — "38 C, where this cell's September 14:00 median is 29 and the
    last decade's highest was 40" is an explanation; a lone boolean is not.
    """
    mad, band = bucket["mad"], _band(value, bucket)
    if mad > 0:
        score = MAD_SCALE * (value - bucket["median"]) / mad
        anomalous = abs(score) >= ANOMALY_Z
        method = "modified_z"
    else:
        # More than half the bucket is one value — the normal state of
        # precipitation. Rank still means something where spread does not.
        score = None
        anomalous = band in ("extremely_low", "extremely_high")
        method = "percentile"

    return {
        "value": round(float(value), 2),
        "band": band,
        "anomalous": anomalous,
        "z": None if score is None else round(score, 2),
        "method": method,
        "median": bucket["median"],
        "p05": bucket["p05"],
        "p95": bucket["p95"],
        "record_low": bucket["minimum"],
        "record_high": bucket["maximum"],
        # Beyond anything in a decade of this bucket. Worth separating from
        # "anomalous", because it means the baseline itself has never seen this.
        "beyond_record": value > bucket["maximum"] or value < bucket["minimum"],
        "samples": bucket["samples"],
    }


def anomalies(
    latitude: float, longitude: float, month: int, hour: int, readings: dict[str, float]
) -> dict[str, Any]:
    """Assess several readings for one place and time against climatology.

    Args:
        latitude: WGS84 degrees north.
        longitude: WGS84 degrees east.
        month: calendar month, 1-12.
        hour: hour of day in UTC, 0-23 — matching how the baselines were built.
        readings: variable name to observed value.

    Returns:
        dict: `cell_id` of the baseline used, `assessed` per variable, and
            `unavailable` listing variables with no bucket. A variable with no
            baseline is named rather than silently dropped, because "we did not
            check" and "we checked and it was fine" must not look alike.
    """
    cell_id = baseline_cell_for(latitude, longitude)
    if cell_id is None:
        return {"cell_id": None, "assessed": {}, "unavailable": sorted(readings),
                "reason": "no_baseline_within_range"}

    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT variable, samples, mean, std, median, mad,
                       p05, p25, p75, p95, minimum, maximum
                FROM weather_baselines
                WHERE cell_id = :cell_id AND month = :month AND hour = :hour
                  AND variable = ANY(:variables)
                """
            ),
            {
                "cell_id": cell_id,
                "month": month,
                "hour": hour,
                "variables": list(readings),
            },
        ).mappings().all()

    buckets = {row["variable"]: dict(row) for row in rows}
    assessed = {
        variable: assess(value, buckets[variable])
        for variable, value in readings.items()
        if variable in buckets
    }
    return {
        "cell_id": cell_id,
        "assessed": assessed,
        "unavailable": sorted(set(readings) - set(assessed)),
    }
