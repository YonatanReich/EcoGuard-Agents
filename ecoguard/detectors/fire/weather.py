"""Finding weather in which a fire would spread.

Emits its own hazard, never a fire. Hot, dry, windy conditions mean a fire
could spread if one started; they are not evidence that anything is burning,
and treating them as such would fill the map with fires nobody reported."""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.database.repositories.climatology import baseline_cell_for
from ecoguard.database.repositories.collector_runs import (
    last_success_at,
    log_finish,
    log_start,
)
from ecoguard.shared.cells import service_area_cells
from ecoguard.shared.signals import (
    FIRE_WEATHER,
    Baseline,
    CellSignal,
    direction_for,
    rarity_from_baseline,
)
from ecoguard.detectors.shared.window import catchup_floor

logger = logging.getLogger(__name__)

# The rows this reads, matching what the Open-Meteo observation collector writes.
SOURCE = "weather"

# What this detector calls itself in `collector_runs`, where its bookmark lives.
RUN_SOURCE = "detector_fire_weather"

# Variable to the unit Open-Meteo was asked for in `open_meteo/client.py`
# (celsius, kmh). The unit rides along on the signal because the coordinator
# compares rarity, not magnitude, and by the time anyone displays the value the
# collector's request parameters are a long way away.
VARIABLES: dict[str, str] = {
    "temperature_2m": "C",
    "relative_humidity_2m": "%",
    "wind_speed_10m": "km/h",
    "vapour_pressure_deficit": "kPa",
}

# Which tail is the worrying one, resolved once at import. `direction_for`
# answers None for a variable nobody has classified, and that must fail here
# rather than on whichever cell happens to be read first - a mid-sweep
# ValueError would abandon every cell after it.
DIRECTIONS = {variable: direction_for(FIRE_WEATHER, variable) for variable in VARIABLES}
if None in DIRECTIONS.values():
    raise ValueError(
        "no fire direction for "
        f"{[name for name, way in DIRECTIONS.items() if way is None]}"
    )

# How old the newest stored hour may be and still describe now. Open-Meteo
# publishes hourly and the collector wakes hourly, so two hours is one missed
# tick of slack. Past that the sweep reports nothing, which is the right answer:
# a stale reading is not evidence about the present, and silence is visible in
# the run log while a confident four-hour-old anomaly is not.
MAX_AGE = timedelta(hours=2)

# How far back to read arrivals when resuming after a gap. One hour more than
# MAX_AGE, which is one missed collector tick of slack: reading further would
# only find readings the sweep then refuses as stale.
CATCHUP = timedelta(hours=3)

# How old an observation may be before it is history rather than news. Wider
# than MAX_AGE because the bookmark, not a window, decides what gets read: this
# only exists to stop a backfill of last year's weather opening incidents.
STALE_AFTER = timedelta(hours=12)


@lru_cache(maxsize=1)
def _baseline_cells() -> dict[str, str]:
    """Which baseline cell answers for each service-area cell.

    Climatology is built on a coarser subgrid than the detection grid - a
    smooth regional field does not need 5 km resolution - so several cells
    share one baseline. Pure arithmetic over the known grid, so this is a
    dictionary built once rather than a lookup per cell per hour.
    """
    mapping = {}
    for cell in service_area_cells():
        baseline_cell = baseline_cell_for(cell.latitude, cell.longitude)
        if baseline_cell is not None:
            mapping[cell.cell_id] = baseline_cell
    return mapping


def latest_readings(at: datetime) -> list[dict[str, Any]]:
    """The most recent measured hour for every cell that has a fresh one.

    `issued_at IS NULL` is what separates a measurement from a forecast - the
    forecast collector writes into the same table and marks its rows with the
    run that produced them. A forecast is a claim about weather that has not
    happened, and detecting on it would open incidents for tomorrow.

    The window is closed at both ends, and the upper bound is not decoration.
    With only a floor, `at` would set where to start looking rather than when
    to pretend it is, and `DISTINCT ON ... ORDER BY observed_at DESC` would
    happily hand back a row stamped after the moment being asked about - a
    replay of last February reading this morning's weather, and in production
    one clock-skewed row outranking every real one.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT ON (cell_id) cell_id, observed_at, payload
                FROM observations
                WHERE source = :source
                  AND issued_at IS NULL
                  AND observed_at BETWEEN :since AND :at
                ORDER BY cell_id, observed_at DESC
                """
            ),
            {"source": SOURCE, "since": at - MAX_AGE, "at": at},
        ).mappings().all()
    return [dict(row) for row in rows]


def arrivals_since(since: datetime | None, at: datetime) -> list[dict[str, Any]]:
    """The newest measured hour per cell among rows stored since the bookmark.

    Driven by `ingested_at` so a detector that missed ticks still sees what
    piled up, rather than silently losing everything older than a window.

    Still one row per cell: unlike a satellite overpass, consecutive weather
    hours for a cell are re-measurements of a continuing state, not separate
    events, and the freshest one is the one that describes now. What the
    bookmark changes is that a cell whose hour arrived while the detector was
    asleep is no longer skipped.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT ON (cell_id) cell_id, observed_at, payload
                FROM observations
                WHERE source = :source
                  AND issued_at IS NULL
                  AND ingested_at > :since
                  AND observed_at BETWEEN :oldest AND :at
                ORDER BY cell_id, observed_at DESC
                """
            ),
            {
                "source": SOURCE,
                "since": since or (at - MAX_AGE),
                "oldest": at - STALE_AFTER,
                "at": at,
            },
        ).mappings().all()
    return [dict(row) for row in rows]


def _baselines(
    cells: set[str], months: set[int], hours: set[int]
) -> dict[tuple[str, str, int, int], Baseline]:
    """Every bucket this sweep could need, in one round trip.

    Keyed by all four of its coordinates because cells do not have to agree on
    which hour is their latest - a collector run that timed out on one batch
    leaves that batch an hour behind, and judging a 14:00 reading against the
    15:00 bucket would be wrong in exactly the way nobody would notice.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT cell_id, variable, month, hour, samples,
                       minimum, p05, p25, median, p75, p95, maximum
                FROM weather_baselines
                WHERE cell_id = ANY(:cells)
                  AND variable = ANY(:variables)
                  AND month = ANY(:months)
                  AND hour = ANY(:hours)
                """
            ),
            {
                "cells": sorted(cells),
                "variables": sorted(VARIABLES),
                "months": sorted(months),
                "hours": sorted(hours),
            },
        ).mappings().all()

    return {
        (row["cell_id"], row["variable"], row["month"], row["hour"]): Baseline(
            minimum=row["minimum"],
            p05=row["p05"],
            p25=row["p25"],
            median=row["median"],
            p75=row["p75"],
            p95=row["p95"],
            maximum=row["maximum"],
            samples=row["samples"],
            origin="weather_baselines",
        )
        for row in rows
    }


def score(
    cell_id: str,
    observed_at: datetime,
    payload: dict[str, Any],
    baseline_cell: str,
    buckets: dict[tuple[str, str, int, int], Baseline],
) -> tuple[list[CellSignal], int]:
    """Judge one cell-hour against its climatology. No database, no filtering.

    Every variable that can be assessed comes back scored, reportable or not,
    because "assessed and ordinary" and "not assessed" are different facts and
    the caller is the one that has to tell them apart. The second element is
    how many variables could not be judged at all.

    Separate from `detect` so the arithmetic can be exercised on readings that
    were never stored - which is the only way to test a detector against
    anomalies whose answer is known in advance.
    """
    signals: list[CellSignal] = []
    unassessed = 0

    for variable, unit in VARIABLES.items():
        value = payload.get(variable)
        baseline = buckets.get(
            (baseline_cell, variable, observed_at.month, observed_at.hour)
        )
        if value is None or baseline is None:
            unassessed += 1
            continue

        signals.append(
            CellSignal(
                cell_id=cell_id,
                observed_at=observed_at,
                hazard=FIRE_WEATHER,
                variable=variable,
                value=float(value),
                unit=unit,
                source=SOURCE,
                rarity=rarity_from_baseline(
                    float(value), baseline, DIRECTIONS[variable]
                ),
                direction=DIRECTIONS[variable],
                baseline=baseline,
                # Which of the coarse baseline cells answered for this one.
                # Without it a surprising rarity cannot be traced back to the
                # distribution that produced it.
                evidence={"baseline_cell": baseline_cell},
            )
        )

    return signals, unassessed


@live_actor("detector.fire_weather")
def detect_new(*, reportable_only: bool = True) -> list[CellSignal]:
    """Everything that arrived since this detector last finished. The live path.

    Same bookmark discipline as the satellite side: read the mark, log the run,
    then read the rows, so the overlap falls on the safe side. A tick that never
    happened costs nothing but latency.
    """
    now = datetime.now(timezone.utc)
    since = catchup_floor(last_success_at(RUN_SOURCE), now, limit=CATCHUP)
    run_id = log_start(RUN_SOURCE)
    try:
        signals = _signals_from(
            arrivals_since(since, now), reportable_only=reportable_only
        )
        log_finish(run_id, status="ok", rows_written=len(signals))
        logger.info(
            "fire weather: %s signals from arrivals since %s",
            len(signals), since or "(first run)",
        )
        return signals
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise


def detect(at: datetime | None = None, *, reportable_only: bool = True) -> list[CellSignal]:
    """Every fire-weather reading unusual enough to be worth reporting.

    Args:
        at: treat this as now, for deciding what counts as a fresh reading.
            Defaults to the wall clock.
        reportable_only: keep only signals at or above `REPORTING_RARITY`.
            Turning it off returns every assessment the sweep made, which is
            what a threshold has to be chosen against - the reportable set
            alone cannot show what sits just underneath it.

    Returns:
        `CellSignal`s. The reportable filter lives here rather than in the
        coordinator because `coordinate` opens an incident for every signal
        handed to it, and the unfiltered sweep is four thousand readings an
        hour of which all but a handful are an ordinary afternoon.

        No location. Weather is a field over the whole cell, not a point in it,
        and `cell_centre_location` is available downstream for anything that
        must draw something. Inventing a centroid here would make a condition
        covering 25 square kilometres look like a fix on a map.
    """
    now = at or datetime.now(timezone.utc)
    readings = latest_readings(now)
    if not readings:
        logger.info("fire weather: no measured hour newer than %s", now - MAX_AGE)
        return []
    return _signals_from(readings, reportable_only=reportable_only)


def _signals_from(
    readings: list[dict[str, Any]], *, reportable_only: bool
) -> list[CellSignal]:
    """Score stored readings. Shared by the live path and by a replay.

    Which rows arrive here is the only thing the bookmark changes; what is made
    of them must stay identical, or the tested path stops being the live one.
    """
    if not readings:
        return []

    baseline_of = _baseline_cells()
    wanted = {
        (baseline_of[row["cell_id"]], row["observed_at"].month, row["observed_at"].hour)
        for row in readings
        if row["cell_id"] in baseline_of
    }
    if not wanted:
        logger.warning(
            "fire weather: %s readings, none within reach of a baseline", len(readings)
        )
        return []

    buckets = _baselines(
        {cell for cell, _, _ in wanted},
        {month for _, month, _ in wanted},
        {hour for _, _, hour in wanted},
    )

    signals: list[CellSignal] = []
    unassessed = 0

    for row in readings:
        baseline_cell = baseline_of.get(row["cell_id"])
        if baseline_cell is None:
            # One count for the whole cell: no baseline in range means none of
            # its variables could be judged, not that each failed separately.
            unassessed += len(VARIABLES)
            continue

        scored, missed = score(
            row["cell_id"], row["observed_at"], row["payload"] or {},
            baseline_cell, buckets,
        )
        signals.extend(scored)
        unassessed += missed

    if reportable_only:
        signals = [signal for signal in signals if signal.reportable]

    logger.info(
        "fire weather: %s cells, %s signals, %s not assessed",
        len(readings), len(signals), unassessed,
    )
    return signals
