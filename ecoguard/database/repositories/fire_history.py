"""What has burned here before, and what only looks like it.

Both answers come from counting stored satellite detections in a radius and a
time window, so there is no extra table to build or keep honest.

The first is fire history: a place that has burned repeatedly is a place fires
start, and that is one of the strongest cheap predictors there is.

The second decides whether the detector is usable at all. Quarries, industrial
flares and landfills trip heat sensors on a schedule, and over weeks they look
exactly like a fire-prone area. They are told apart by regularity rather than
count: a bad fire season puts many detections in one place too, but it does not
put them there on most days, month after month."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session

SOURCE = "firms"

# The three windows the historical feature set is defined over. Widening radius
# as the window lengthens is deliberate: recent fire matters close by, where it
# changed the fuel; old fire matters as a regional tendency.
HISTORY_WINDOWS = (
    ("fires_within_5km_previous_30d", 5_000, 30),
    ("fires_within_10km_previous_90d", 10_000, 90),
    ("fires_within_25km_previous_365d", 25_000, 365),
)

# How long a record has to be before persistence means anything. Below this,
# "detected on most days" is just "detected twice last week".
PERSISTENCE_MIN_DAYS = 60

# Share of days in the window carrying a detection, above which a location is
# treated as a standing thermal source rather than a fire-prone one. A real
# fire regime, even a severe one, does not light the same 5 km cell on two
# days out of five for two months.
PERSISTENCE_DAY_SHARE = 0.4


def fire_history(latitude: float, longitude: float, at: datetime | None = None) -> dict[str, Any]:
    """Counts of prior detections around a point, plus how long since the last.

    Args:
        latitude: WGS84 degrees north.
        longitude: WGS84 degrees east.
        at: evaluate as of this moment; defaults to now. Pass the event time
            when scoring a past event, so the answer uses only what was
            already known then rather than everything known since.

    Returns:
        dict: one count per window in HISTORY_WINDOWS, and
            `days_since_previous_detection_within_10km` — None when nothing has
            ever been detected there, which is a real state and not a zero.
    """
    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    counts = ",\n          ".join(
        f"""count(*) FILTER (
            WHERE ST_DWithin(location, origin, {radius})
              AND observed_at >= :moment - interval '{days} days'
          ) AS {name}"""
        for name, radius, days in HISTORY_WINDOWS
    )

    with Session() as session:
        row = session.execute(
            text(
                f"""
                WITH origin AS (
                  SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography AS origin
                )
                SELECT
                  {counts},
                  max(observed_at) FILTER (
                    WHERE ST_DWithin(location, origin, 10000)
                  ) AS most_recent
                FROM observations, origin
                WHERE source = :source
                  AND observed_at <= :moment
                  AND observed_at >= :moment - interval '365 days'
                  AND location IS NOT NULL
                """
            ),
            {"latitude": latitude, "longitude": longitude, "moment": moment, "source": SOURCE},
        ).mappings().one()

    most_recent = row["most_recent"]
    return {
        **{name: int(row[name]) for name, _, _ in HISTORY_WINDOWS},
        "days_since_previous_detection_within_10km": (
            None if most_recent is None
            else round((moment - most_recent).total_seconds() / 86400, 2)
        ),
    }


def persistence(cell_id: str, at: datetime | None = None) -> dict[str, Any]:
    """Whether a cell's hotspot record looks like industry rather than fire.

    Args:
        cell_id: the 5 km service-area cell to assess.
        at: evaluate as of this moment; defaults to now.

    Returns:
        dict: `persistent` (bool), the `distinct_days` carrying a detection,
            the `span_days` those are spread over, the resulting `day_share`,
            and `reason`. `persistent` is False with a reason of
            "insufficient_history" while a cell is too new to judge — that is
            an admission, not a clearance, and a caller should not read it as
            "confirmed real".

    A caller that finds `persistent` True should not discard the detection. It
    should stop *alerting* on it: a flare stack that also catches the brush
    around it is exactly the case where the record is misleading and the fire
    is real.
    """
    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with Session() as session:
        row = session.execute(
            text(
                """
                SELECT
                  count(DISTINCT date_trunc('day', observed_at)) AS distinct_days,
                  min(observed_at) AS first_seen,
                  max(observed_at) AS last_seen
                FROM observations
                WHERE source = :source AND cell_id = :cell_id
                  AND observed_at <= :moment
                  AND observed_at >= :moment - interval '365 days'
                """
            ),
            {"cell_id": cell_id, "moment": moment, "source": SOURCE},
        ).mappings().one()

    distinct_days = int(row["distinct_days"] or 0)
    if not distinct_days:
        return _verdict(False, 0, 0, "never_detected")

    span_days = max(1, round((row["last_seen"] - row["first_seen"]).total_seconds() / 86400) + 1)
    if span_days < PERSISTENCE_MIN_DAYS:
        return _verdict(False, distinct_days, span_days, "insufficient_history")

    share = distinct_days / span_days
    return _verdict(
        share >= PERSISTENCE_DAY_SHARE,
        distinct_days,
        span_days,
        "standing_thermal_source" if share >= PERSISTENCE_DAY_SHARE else "episodic",
    )


def _verdict(persistent: bool, distinct_days: int, span_days: int, reason: str) -> dict[str, Any]:
    """Whether a place's hotspots look like an industrial source, and why."""
    return {
        "persistent": persistent,
        "distinct_days": distinct_days,
        "span_days": span_days,
        "day_share": round(distinct_days / span_days, 3) if span_days else 0.0,
        "reason": reason,
    }
