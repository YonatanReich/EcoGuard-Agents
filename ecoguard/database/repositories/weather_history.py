"""The one place anything reads stored weather.

Before this module there were three Open-Meteo callers: the scheduled
collector writing Postgres, a rolling SQLite cache feeding the fire-risk
model, and WeatherDataAgent calling the provider live on every HTTP request.
Three fetch paths meant three rate-limiter states that could not see each
other, two copies of the same seven variables, and a per-request provider call
on the hot path of an endpoint that already took thirty seconds.

Now the collector is the only thing that talks to Open-Meteo, and everything
else reads here. The three consumers want three different shapes of the same
rows, which is what the three public functions are:

  * `missing_hours`   — the collector asking what it still has to fetch
  * `hourly_for_cell` — the fire-risk model's 168-hour feature window
  * `current_for_point` — one coordinate's latest reading, for the API
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.collection.shared.open_meteo.client import HOURLY_VARIABLES

SOURCE = "weather"

# What compute_features needs behind an evaluation time: seven days of hourly
# history. The collector backfills to this depth, so a freshly migrated
# database fills itself instead of waiting a week to answer.
HISTORY_HOURS = 168

# How old the newest reading may be and still be reported as current. The
# collector writes complete hours only, so one or two hours of lag is normal
# and anything past this means collection is down — in which case saying so
# beats serving yesterday's temperature as today's.
CURRENT_MAX_AGE_HOURS = 6

# How far from a coordinate to look for a cell. The grid is 5 km, so the
# furthest a point inside a cell can sit from that cell's centre is about
# 3.5 km; the extra allows a point just outside the service area to still be
# answered by the cell it borders.
CELL_REACH_M = 5_000


def _hour(value: datetime) -> datetime:
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def missing_hours(
    cell_ids: Sequence[str], start: datetime, end: datetime
) -> dict[str, list[datetime]]:
    """Return, per cell, the hours in [start, end] that are not stored yet.

    This is what replaced the collector's fixed lookback window. A fixed window
    could only ever repair an outage shorter than itself — an outage of nine
    hours against a six-hour window left three hours that nothing would ever go
    back for, and the production table had thirteen such hours in sixty-seven.
    Asking the database what is actually absent makes the size of the fetch
    match the size of the gap: one hour normally, the whole gap after an
    outage, and seven days on an empty table.

    Two queries rather than one anti-join over cells x hours. That join is
    ~200,000 index probes and returns a row per missing pair; the counts below
    are one index range scan returning at most `HISTORY_HOURS` rows. Only hours
    that are *partly* stored need resolving per cell, and those are rare — an
    hour is written for every cell in one batch or not at all.
    """
    first, last = _hour(start), _hour(end)
    if last < first or not cell_ids:
        return {}

    wanted_hours = [
        first + timedelta(hours=step)
        for step in range(int((last - first).total_seconds() // 3600) + 1)
    ]
    expected = len(cell_ids)

    with Session() as session:
        # The identity constraint makes (source, cell_id, observed_at) unique,
        # so the count per hour is already the number of distinct cells.
        counts = dict(session.execute(
            text(
                """
                SELECT observed_at, count(*)
                FROM observations
                WHERE source = :source
                  AND observed_at BETWEEN CAST(:first AS timestamptz)
                                      AND CAST(:last AS timestamptz)
                GROUP BY observed_at
                """
            ),
            {"source": SOURCE, "first": first, "last": last},
        ).all())

        absent = [hour for hour in wanted_hours if hour not in counts]
        partial = [hour for hour, stored in counts.items() if stored != expected]

        stored_by_hour: dict[datetime, set[str]] = {}
        if partial:
            for hour, cell_id in session.execute(
                text(
                    """
                    SELECT observed_at, cell_id
                    FROM observations
                    WHERE source = :source
                      AND observed_at = ANY(CAST(:hours AS timestamptz[]))
                    """
                ),
                {"source": SOURCE, "hours": partial},
            ).all():
                stored_by_hour.setdefault(hour, set()).add(cell_id)

    gaps: dict[str, list[datetime]] = {}
    for cell_id in cell_ids:
        missing = list(absent)
        for hour in partial:
            if cell_id not in stored_by_hour.get(hour, set()):
                missing.append(hour)
        if missing:
            gaps[cell_id] = sorted(missing)
    return gaps


def contiguous_ranges(hours: Iterable[datetime]) -> list[tuple[datetime, datetime]]:
    """Collapse sorted hours into inclusive (start, end) runs.

    One request per run rather than per hour: a seven-day backfill is one call
    per cell batch, not a hundred and sixty-eight.
    """
    ordered = sorted(set(hours))
    if not ordered:
        return []
    runs = [[ordered[0], ordered[0]]]
    for hour in ordered[1:]:
        if hour - runs[-1][1] == timedelta(hours=1):
            runs[-1][1] = hour
        else:
            runs.append([hour, hour])
    return [(run[0], run[1]) for run in runs]


# The seven stored variables, unpacked in SQL rather than shipped as jsonb.
# A national scan reads ~200,000 rows; sending seven floats per row instead of
# a JSON object per row is most of the transfer.
_VALUE_COLUMNS = ", ".join(
    f"(payload->>'{variable}')::double precision AS {variable}"
    for variable in HOURLY_VARIABLES
)


def _empty_series() -> dict[str, list[Any]]:
    return {"time": [], **{variable: [] for variable in HOURLY_VARIABLES}}


def hourly_for_cells(
    cell_ids: Sequence[str], start: datetime, end: datetime
) -> dict[str, dict[str, Any]]:
    """Stored hours for many cells at once, in the shape compute_features wants.

    compute_features is pure — it takes {"status", "hourly": {"time": [...],
    "temperature_2m": [...], ...}} and an evaluation time, and does not care
    whether those lists came from a provider response, a SQLite cache or this
    query. That is what let the fire-risk model move off its private cache
    without touching the model or a single feature definition.

    Bulk because the national scan asks for every cell at one evaluation time.
    One query for 1,174 cells rather than 1,174 queries: against a hosted
    Postgres the round trip dominates, so the per-cell form turned a scan into
    something like a quarter of an hour of pure latency.

    `status` is "success" only when every hour of the window is present, so a
    partially collected window degrades the model's own status instead of
    quietly yielding features computed from a series full of holes.
    """
    first, last = _hour(start), _hour(end)
    wanted = max(0, int((last - first).total_seconds() // 3600) + 1)
    series: dict[str, dict[str, list[Any]]] = {cell_id: _empty_series() for cell_id in cell_ids}
    if not cell_ids or last < first:
        return {
            cell_id: {"status": "partial", "hourly": _empty_series(),
                      "stored_hours": 0, "missing_hours": wanted}
            for cell_id in cell_ids
        }

    with Session() as session:
        rows = session.execute(
            text(
                f"""
                SELECT cell_id, observed_at, {_VALUE_COLUMNS}
                FROM observations
                WHERE source = :source
                  AND cell_id = ANY(CAST(:cell_ids AS text[]))
                  AND observed_at BETWEEN CAST(:first AS timestamptz)
                                      AND CAST(:last AS timestamptz)
                ORDER BY cell_id, observed_at
                """
            ),
            {"source": SOURCE, "cell_ids": list(cell_ids), "first": first, "last": last},
        ).mappings().all()

    for row in rows:
        hourly = series.get(row["cell_id"])
        if hourly is None:
            continue
        # Naive ISO text, matching what compute_features parses: it appends UTC
        # itself, and an offset in the string would be applied twice.
        hourly["time"].append(
            row["observed_at"].astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        )
        for variable in HOURLY_VARIABLES:
            hourly[variable].append(row[variable])

    return {
        cell_id: {
            "status": "success" if len(hourly["time"]) >= wanted else "partial",
            "hourly": hourly,
            "stored_hours": len(hourly["time"]),
            "missing_hours": max(0, wanted - len(hourly["time"])),
        }
        for cell_id, hourly in series.items()
    }


def hourly_for_cell(cell_id: str, start: datetime, end: datetime) -> dict[str, Any]:
    """One cell's stored hours. See `hourly_for_cells`."""
    return hourly_for_cells([cell_id], start, end)[cell_id]


def current_for_point(latitude: float, longitude: float) -> dict[str, Any] | None:
    """The newest reading from the grid cell nearest a coordinate.

    Returns None when no cell within reach has a recent enough reading, which
    the caller reports as a collection failure rather than papering over.

    Ordering by distance then time picks the nearest cell's latest row:
    distance is constant within a cell, so the first tie-break group is one
    cell and the second orders that cell's rows.

    The `distance_m` and `cell_id` come back with the reading because this is a
    grid answer to a point question. A caller that needs to know it is looking
    at a 5 km cell centre rather than the exact coordinate can see it.
    """
    with Session() as session:
        row = session.execute(
            text(
                """
                SELECT cell_id,
                       observed_at,
                       payload,
                       ST_Y(location::geometry) AS latitude,
                       ST_X(location::geometry) AS longitude,
                       ST_Distance(
                         location,
                         ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
                       ) AS distance_m
                FROM observations
                WHERE source = :source
                  AND location IS NOT NULL
                  AND observed_at >= now() - make_interval(hours => :max_age)
                  AND ST_DWithin(
                        location,
                        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                        :reach
                      )
                ORDER BY distance_m, observed_at DESC
                LIMIT 1
                """
            ),
            {
                "source": SOURCE,
                "latitude": latitude,
                "longitude": longitude,
                "max_age": CURRENT_MAX_AGE_HOURS,
                "reach": CELL_REACH_M,
            },
        ).mappings().first()

    if row is None:
        return None
    return {
        "cell_id": row["cell_id"],
        "observed_at": row["observed_at"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "distance_m": round(row["distance_m"], 1),
        **{variable: (row["payload"] or {}).get(variable) for variable in HOURLY_VARIABLES},
    }


def wind_for_point_at(
    latitude: float,
    longitude: float,
    *,
    at: datetime,
    maximum_age_seconds: float,
    sources: Sequence[str] = (SOURCE,),
    maximum_distance_m: float | None = None,
) -> dict[str, Any] | None:
    """Return the nearest fresh measured wind row at or before ``at``.

    This is an event-time read, unlike :func:`current_for_point`, whose public
    contract intentionally remains tied to the database wall clock.  Callers
    choose the accepted observation sources and freshness window.  Forecasts
    are excluded structurally by requiring ``issued_at IS NULL``.
    """

    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("at must carry a UTC offset")
    if (
        isinstance(maximum_age_seconds, bool)
        or not isinstance(maximum_age_seconds, (int, float))
        or not math.isfinite(float(maximum_age_seconds))
        or maximum_age_seconds <= 0
    ):
        raise ValueError("maximum_age_seconds must be positive")
    accepted_sources = [
        source.strip()
        for source in sources
        if isinstance(source, str) and source.strip()
    ]
    if not accepted_sources or len(accepted_sources) != len(sources):
        raise ValueError("sources must contain non-empty source names")
    if maximum_distance_m is not None and (
        isinstance(maximum_distance_m, bool)
        or not isinstance(maximum_distance_m, (int, float))
        or not math.isfinite(float(maximum_distance_m))
        or maximum_distance_m <= 0
    ):
        raise ValueError("maximum_distance_m must be positive when supplied")

    reference = at.astimezone(timezone.utc)
    distance_filter = (
        "AND ST_DWithin(location, origin.point, :maximum_distance_m)"
        if maximum_distance_m is not None
        else ""
    )
    with Session() as session:
        row = session.execute(
            text(
                f"""
                WITH origin AS (
                  SELECT ST_SetSRID(
                    ST_MakePoint(:longitude, :latitude), 4326
                  )::geography AS point
                )
                SELECT source,
                       cell_id,
                       observed_at,
                       payload,
                       ST_Y(location::geometry) AS latitude,
                       ST_X(location::geometry) AS longitude,
                       ST_Distance(location, origin.point) AS distance_m
                FROM observations, origin
                WHERE source = ANY(CAST(:sources AS text[]))
                  AND issued_at IS NULL
                  AND location IS NOT NULL
                  AND observed_at <= CAST(:at AS timestamptz)
                  AND observed_at >= CAST(:at AS timestamptz)
                      - make_interval(secs => :maximum_age_seconds)
                  AND payload ? 'wind_speed_10m'
                  AND payload ? 'wind_direction_10m'
                  AND jsonb_typeof(payload->'wind_speed_10m') = 'number'
                  AND jsonb_typeof(payload->'wind_direction_10m') = 'number'
                  AND (payload->>'wind_speed_10m')::double precision >= 0
                  AND (payload->>'wind_direction_10m')::double precision >= 0
                  AND (payload->>'wind_direction_10m')::double precision < 360
                  {distance_filter}
                ORDER BY distance_m, observed_at DESC, source, cell_id
                LIMIT 1
                """
            ),
            {
                "sources": accepted_sources,
                "latitude": latitude,
                "longitude": longitude,
                "at": reference,
                "maximum_age_seconds": float(maximum_age_seconds),
                "maximum_distance_m": maximum_distance_m,
            },
        ).mappings().first()

    if row is None:
        return None
    return {
        "source": row["source"],
        "cell_id": row["cell_id"],
        "observed_at": row["observed_at"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "distance_m": round(row["distance_m"], 1),
        "payload": dict(row["payload"] or {}),
    }
