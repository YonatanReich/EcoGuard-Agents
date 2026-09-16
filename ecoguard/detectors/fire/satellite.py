"""The detector that can actually see a fire.

Everything else in this package infers. A FIRMS hotspot is a measurement of
something burning right now: the instrument registered radiative power at a
place, at a time. That is why this is the originating detector and the weather
sweep is a corroborator - no threshold on temperature or humidity will ever
tell you a fire has started, because the weather feed is a numerical model that
has no knowledge one exists.

The one thing that makes this hard
----------------------------------
The satellite is indiscriminate. It sees the fire in the Galilee and it sees a
steel works in the Rishon LeZion industrial belt, which lights on most nights,
always between 22:52 and 00:33, always at 0.5-2.0 MW. Reported naively that is
an emergency incident every night forever, and a queue that cries wolf nightly
is worse than no queue at all, because people stop reading it.

So every detection is weighed against how often *that cell* lights up anyway,
from `firms_baselines`. This is `rarity_from_rate` in shared/signals.py finally
having something to read: a cell that has never lit in a year scores 1.0, and
a cell that lights half the time scores 0.5 and stays out of the queue.

Why the reporting bar is not REPORTING_RARITY
---------------------------------------------
0.999 is calibrated in shared/signals.py for a continuous variable sampled
hourly across 1,174 cells - 28,176 draws a day, where a one-in-a-thousand bar
still lets 28 through. None of that describes this source. FIRMS produces a
handful of detections a day nationally, and the question is not "how extreme is
this number" but "is this cell a known furnace". Applied here, 0.999 would
demand a cell with *zero* prior detections in the whole window, which would
suppress any cell that had a single fire last year - the exact opposite of what
the baseline is for.

The bar is therefore the persistence question stated plainly: a cell that lights
on more than one day in twenty is somebody's industry, and anything quieter than
that is worth a look.

What travels downstream
-----------------------
The coordinator dedupes these against each other and against the weather sweep,
then routes to the analysers for severity and spread. Both of those need things
a bare "there is a fire in cell X" cannot give, so each signal carries:

  * a real **location** - the FRP-weighted centroid of the actual pixels, not
    the cell centroid, with a precision that widens to cover their spread. A
    crew is dispatched to a point; four pixels strung over two kilometres is a
    two-kilometre fire and must not be drawn as a confident dot.
  * **peak FRP** as the value, in megawatts - the intensity term any spread
    model starts from.
  * the **recent overpass history** in evidence, so the analyser can see
    4.7 -> 18.6 -> 71.6 MW and know the fire is growing rather than guess from
    a single frame.
  * **confidence** from the instrument's own flag and how many satellites
    agree, kept separate from rarity because "the pixel may be noise" and "this
    cell burns every night" are different doubts and have different remedies.

Severity stays None. How dangerous this is depends on what is downwind and who
lives there, and that is the analysers' job.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.database.repositories.collector_runs import (
    last_success_at,
    log_finish,
    log_start,
)
from ecoguard.shared.signals import (
    FIRE,
    GEOSTATIONARY_PIXEL_M,
    HIGH,
    MODIS_PIXEL_M,
    VIIRS_PIXEL_M,
    CellSignal,
    locate_points,
    rarity_from_rate,
)

logger = logging.getLogger(__name__)

SOURCE = "firms"

# What this detector calls itself in `collector_runs`. Separate from SOURCE,
# which names the rows it reads: one is what it consumes, the other is what it
# is, and the bookmark belongs to the latter.
RUN_SOURCE = "detector_fire_satellite"

# The claim being made about a cell, in the units the instrument reports.
VARIABLE = "frp"
UNIT = "MW"

# How old a detection may be and still describe what is happening now.
#
# Longer than the weather sweep's two hours, for a reason that is about the
# source rather than about patience: near-real-time FIRMS runs about three
# hours behind the overpass, so a two-hour window would discard the data on
# arrival. Six hours also matches the fire quiet period in the coordinator, so
# a detection can still find the incident it belongs to.
MAX_AGE = timedelta(hours=6)

# How much of the recent past to hand the analysers as the growth curve.
HISTORY = timedelta(hours=24)

# How old an *observation* may be before storing it counts as history rather
# than news. Only a backfill produces rows this stale; without the bound, one
# would open incidents for fires that burned out months ago.
STALE_AFTER = timedelta(days=1)

# A cell that lights on more than one day in twenty is somebody's industry, not
# a series of fires. See the module docstring for why this is not
# REPORTING_RARITY.
PERSISTENT_SHARE = 0.05
RARITY_BAR = 1.0 - PERSISTENT_SHARE

# FIRMS reports confidence on three different scales and never says which:
#
#   VIIRS       l / n / h
#   MODIS       0-100, a percentage
#   Meteosat    0-1, a fraction        (via the GOES_NRT data_id)
#
# Reading the scale off the value would be a coin toss on a MODIS "1", which is
# one percent on its scale and total certainty on Meteosat's. The product it
# came from is the only thing that settles it, so that is what decides.
VIIRS_CONFIDENCE = {"h": 1.0, "n": 0.8, "l": 0.5}

# Products whose confidence is already a 0-1 fraction, and whose pixels are
# geostationary rather than polar.
GEOSTATIONARY_SOURCES = frozenset({"GOES_NRT"})

# Confidence travels on the signal; it does not gate it. A low-confidence pixel
# is weak evidence of a fire, and this system's answer to weak evidence is
# corroboration in the coordinator - the same reasoning that makes
# `corroborates()` refuse to filter on `reportable`. Discarding it here would
# throw away one half of a pair before the other half could arrive, and the
# cost of being wrong in that direction is a missed fire.


def _pixel_confidence(pixel: dict[str, Any]) -> float:
    """One pixel's trustworthiness, on whichever scale its product reports."""
    raw = pixel.get("confidence")
    if raw is None:
        return 0.5

    if isinstance(raw, str):
        text_value = raw.strip().lower()
        if text_value in VIIRS_CONFIDENCE:
            return VIIRS_CONFIDENCE[text_value]
        try:
            number = float(text_value)
        except ValueError:
            return 0.5
    else:
        number = float(raw)

    # Already a fraction. Dividing it again would turn Meteosat's 0.94 - about
    # as sure as that product ever gets - into 0.0094, and the signal would look
    # like noise.
    if str(pixel.get("firms_source", "")) in GEOSTATIONARY_SOURCES:
        return max(0.0, min(1.0, number))
    return max(0.0, min(1.0, number / 100.0))


def confidence_of(pixels: list[dict[str, Any]], satellites: int) -> float:
    """How much to trust that something is burning here at all.

    The best pixel sets the floor, because one confident detection is not made
    doubtful by a weaker one beside it. Independent satellites then raise it:
    two instruments on separate overpasses seeing the same cell is a different
    claim from one instrument seeing it twice, and the failure modes that
    produce false pixels - glint, a hot roof, a cloud edge - do not usually
    survive a different look angle at a different hour.
    """
    if not pixels:
        return 0.5
    best = max(_pixel_confidence(pixel) for pixel in pixels)
    if satellites > 1:
        best = min(1.0, best + 0.1 * (satellites - 1))
    return round(best, 3)


def _precision_for(pixels: list[dict[str, Any]]) -> float:
    """The coarsest instrument contributing sets the floor on precision.

    A MODIS pixel is 1 km against VIIRS's 375 m. Averaging them and claiming
    the finer figure would invent precision the coarse instrument never had.
    """
    sources = {str(pixel.get("firms_source", "")) for pixel in pixels}
    if sources & GEOSTATIONARY_SOURCES:
        return GEOSTATIONARY_PIXEL_M
    if any("MODIS" in source.upper() for source in sources):
        return MODIS_PIXEL_M
    return VIIRS_PIXEL_M


def detection_rates() -> dict[str, tuple[int, int]]:
    """Per cell: (days it lit, days observed), from the backfilled baseline."""
    with Session() as session:
        rows = session.execute(
            text("SELECT cell_id, detection_days, days_observed FROM firms_baselines")
        ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def arrivals_since(since: datetime | None, at: datetime) -> list[dict[str, Any]]:
    """Every detection stored since the bookmark, oldest arrival first.

    `ingested_at`, not `observed_at`. The difference is the whole point: FIRMS
    publishes about three hours behind the overpass, so a detection's
    observation time is always in the past and a window on it would decide what
    to process by how late the provider was. `ingested_at` asks the only
    question that matters to a detector waking up - what is here that I have
    not seen?

    It is also stamped once per collector batch, so a read can never catch half
    of one, and there is an index on (source, ingested_at) waiting for exactly
    this query.

    `at` still bounds `observed_at`, but as a sanity check rather than a
    window: a year-old backfill landing in the table should not open incidents
    for fires that burned out long ago.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT cell_id, observed_at, payload
                FROM observations
                WHERE source = :source
                  AND ingested_at > :since
                  AND observed_at BETWEEN :oldest AND :at
                ORDER BY ingested_at, observed_at
                """
            ),
            {
                "source": SOURCE,
                # No bookmark yet means a first run, which takes the recent past
                # rather than the entire table.
                "since": since or (at - MAX_AGE),
                "oldest": at - STALE_AFTER,
                "at": at,
            },
        ).mappings().all()
    return [dict(row) for row in rows]


def latest_detections(at: datetime) -> list[dict[str, Any]]:
    """The most recent overpass per cell inside the freshness window.

    One signal per cell rather than one per overpass: three satellites crossing
    within an hour are three looks at one fire, and handing the coordinator
    three signals would inflate an incident's signal count with copies of the
    same event. The other looks are not discarded - they come back in
    `recent_detections` as the growth curve.

    Closed at both ends so `at` means "treat this as now" rather than "start
    looking here", which is what makes a replay of last week reproducible.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT ON (cell_id) cell_id, observed_at, payload
                FROM observations
                WHERE source = :source
                  AND observed_at BETWEEN :since AND :at
                ORDER BY cell_id, observed_at DESC
                """
            ),
            {"source": SOURCE, "since": at - MAX_AGE, "at": at},
        ).mappings().all()
    return [dict(row) for row in rows]


def recent_detections(cells: list[str], at: datetime) -> dict[str, list[dict[str, Any]]]:
    """Every overpass per cell over the last day, oldest first.

    This is the growth curve. A single frame says a fire exists; the sequence
    says whether it is taking hold or dying down, and a spread model that gets
    only the frame is guessing at the term that matters most.
    """
    if not cells:
        return {}
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT cell_id, observed_at, payload
                FROM observations
                WHERE source = :source
                  AND cell_id = ANY(:cells)
                  AND observed_at BETWEEN :since AND :at
                ORDER BY cell_id, observed_at
                """
            ),
            {"source": SOURCE, "cells": cells, "since": at - HISTORY, "at": at},
        ).mappings().all()

    history: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        payload = row["payload"] or {}
        history.setdefault(row["cell_id"], []).append({
            "observed_at": row["observed_at"].isoformat(),
            "peak_frp_mw": payload.get("peak_frp_mw"),
            "hotspot_count": payload.get("hotspot_count"),
            "satellites": payload.get("satellite_sources"),
        })
    return history


def detect_new(*, reportable_only: bool = True) -> list[CellSignal]:
    """Everything that arrived since this detector last finished. The live path.

    The bookmark is this detector's own last successful run in `collector_runs`,
    so a tick that never happened is not a tick whose data is lost - whatever
    piled up while the process was down is read on the next wake-up, however
    long that took.

    The run is logged after the bookmark is read and before the rows are, which
    is what makes the overlap fall on the safe side: anything ingested during
    the read is seen now and again next time. The coordinator absorbs the
    repeat. Nothing is dropped.
    """
    since = last_success_at(RUN_SOURCE)
    run_id = log_start(RUN_SOURCE)
    try:
        now = datetime.now(timezone.utc)
        signals = _signals_from(
            arrivals_since(since, now), now, reportable_only=reportable_only
        )
        log_finish(run_id, status="ok", rows_written=len(signals))
        logger.info(
            "firms: %s signals from arrivals since %s",
            len(signals), since or "(first run)",
        )
        return signals
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise


def detect(at: datetime | None = None, *, reportable_only: bool = True) -> list[CellSignal]:
    """Every satellite hotspot that is not a cell's usual behaviour.

    Args:
        at: treat this as now. Defaults to the wall clock; passing it makes a
            run reproducible and lets a past fire be replayed.
        reportable_only: drop cells that light up routinely. Turning it off
            returns every detection with its rate attached, which is how the
            persistence bar gets judged against what it is excluding.

    Returns:
        `CellSignal`s carrying a real location, peak FRP, instrument
        confidence and the recent growth curve - see the module docstring for
        why each is needed downstream.

        A cell with no baseline row still produces a signal, with rarity None
        and a note in evidence. That is deliberate: an unknown cell is not a
        quiet one, and staying silent about a fire because the backfill has
        not reached that cell yet is the worst failure available here.
    """
    now = at or datetime.now(timezone.utc)
    detections = latest_detections(now)
    if not detections:
        logger.info("firms: no detection newer than %s", now - MAX_AGE)
        return []
    return _signals_from(detections, now, reportable_only=reportable_only)


def _signals_from(
    detections: list[dict[str, Any]], now: datetime, *, reportable_only: bool
) -> list[CellSignal]:
    """Turn stored detections into signals. Shared by both entry points.

    Which rows arrive here is the only difference between the live path and a
    replay; what is made of them must not be, or the thing under test stops
    being the thing that runs.
    """
    if not detections:
        return []

    rates = detection_rates()
    if not rates:
        logger.warning(
            "firms: firms_baselines is empty - every detection will be reported "
            "unweighed, including known industrial sources. "
            "Run: python -m ecoguard.scripts.build_firms_baselines"
        )
    history = recent_detections([row["cell_id"] for row in detections], now)

    signals: list[CellSignal] = []
    for row in detections:
        payload = row["payload"] or {}
        pixels = payload.get("hotspots") or []
        satellites = payload.get("satellite_sources") or []

        detection_days, days_observed = rates.get(row["cell_id"], (None, None))
        if days_observed:
            share = detection_days / days_observed
            rarity = rarity_from_rate(share)
        else:
            share, rarity = None, None

        location = locate_points(
            [
                (pixel["latitude"], pixel["longitude"], float(pixel.get("frp") or 0.0))
                for pixel in pixels
                if pixel.get("latitude") is not None and pixel.get("longitude") is not None
            ],
            pixel_precision_m=_precision_for(pixels),
            method="frp_weighted_centroid",
        )

        signals.append(
            CellSignal(
                cell_id=row["cell_id"],
                observed_at=row["observed_at"],
                hazard=FIRE,
                variable=VARIABLE,
                value=float(payload.get("peak_frp_mw") or 0.0),
                unit=UNIT,
                source=SOURCE,
                rarity=rarity,
                # Radiative power: more of it is worse, always.
                direction=HIGH,
                location=location,
                confidence=confidence_of(pixels, len(satellites)),
                evidence={
                    "hotspot_count": payload.get("hotspot_count"),
                    "satellites": satellites,
                    "pixels": pixels,
                    # The growth curve, for spread prediction.
                    "recent_detections": history.get(row["cell_id"], []),
                    # Why this rarity, so a suppressed cell can be argued with.
                    "detection_days": detection_days,
                    "days_observed": days_observed,
                    "detection_share": None if share is None else round(share, 4),
                },
            )
        )

    if reportable_only:
        kept = []
        for signal in signals:
            if signal.rarity is not None and signal.rarity < RARITY_BAR:
                logger.info(
                    "firms: %s suppressed, lights %.0f%% of days (%s of %s)",
                    signal.cell_id,
                    100 * (1 - signal.rarity),
                    signal.evidence["detection_days"],
                    signal.evidence["days_observed"],
                )
                continue
            kept.append(signal)
        signals = kept

    logger.info(
        "firms: %s cells with a fresh detection, %s reported",
        len(detections), len(signals),
    )
    return signals
