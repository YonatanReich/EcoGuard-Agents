"""Measuring how often each cell shows a satellite hotspot anyway, so an ordinary one is not read as news."""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from ecoguard.collectors.fire.firms.client import FirmsDataAgent, FirmsProviderError
from ecoguard.collectors.fire.firms.collector import _service_area_box
from ecoguard.database.engine import Session
from ecoguard.detectors.fire import signature
from ecoguard.shared.cells import cell_for, service_area_cells

# FIRMS refuses anything larger: the area endpoint answers "Invalid day range.
# Expects [1..5]" and returns HTTP 400. It is five, not the ten the wider FIRMS
# documentation quotes for other endpoints, and getting this wrong is silent in
# the worst way - every window is rejected, the run still "succeeds", and the
# baseline it writes is a few days of data wearing a year's denominator. Which
# is precisely what happened on the first two attempts.
MAX_DAY_RANGE = 5

DEFAULT_DAYS = 365

# Near-real-time products cover roughly the last two months; beyond that the
# standard-processing archive is both the only option and the better data.
NRT_HORIZON_DAYS = 55

NRT_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")
ARCHIVE_SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "MODIS_SP")

# The geostationary feed is its own case in two ways: it serves the full year
# from one data_id rather than splitting into NRT and reprocessed archive, and
# the endpoint caps its day_range at two rather than five. It must be in the
# baseline because it is in the live collector - a cell weighed against a rate
# built from fewer products than now watch it looks quieter than it is, and
# that is the direction that lets an industrial site through.
GEOSTATIONARY_SOURCES = ("GOES_NRT",)
GEOSTATIONARY_DAY_RANGE = 2

# FIRMS publishes a transaction limit per key rather than a documented rate, so
# this is politeness rather than a measured requirement.
REQUEST_SPACING_SECONDS = 1.0

# A transient failure that is quietly skipped lowers a cell's detection count
# and so raises its rarity, turning a furnace into a fire. Worth retrying for.
MAX_ATTEMPTS = 4

# How much of the window may go unfetched before the result is not worth
# storing. Low on purpose: this table's whole job is suppression, and a gappy
# build fails in the direction that suppresses nothing.
MAX_GAP_SHARE = 0.05


def sources_for(window_start: date, today: date) -> tuple[str, ...]:
    """Which polar products can answer for a window starting then."""
    if (today - window_start).days <= NRT_HORIZON_DAYS:
        return NRT_SOURCES
    return ARCHIVE_SOURCES


def windows(days: int, today: date, day_range: int = MAX_DAY_RANGE) -> list[tuple[date, int]]:
    """(start, length) pairs walking backwards, none longer than FIRMS allows."""
    spans = []
    remaining = days
    start = today - timedelta(days=days - 1)
    while remaining > 0:
        length = min(day_range, remaining)
        spans.append((start, length))
        start += timedelta(days=length)
        remaining -= length
    return spans


def fetch_window(
    agent: FirmsDataAgent, box, start: date, length: int, today: date,
    sleep=time.sleep, sources: tuple[str, ...] | None = None,
) -> tuple[list[dict], int]:
    """Every hotspot any product saw in one window, and how many gave up.

    Retries before conceding, because a skipped window is not a neutral loss
    here: it lowers a cell's detection count, which *raises* its rarity, which
    makes a furnace look like a fire. The first run of this script silently
    dropped two months to transient errors and produced a baseline that would
    have failed to suppress the one industrial site we know about. A gap has to
    be loud.
    """
    latitude, longitude, delta = box
    hotspots: list[dict] = []
    failures = 0

    for source in (sources if sources is not None else sources_for(start, today)):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = agent.fetch_hotspots(
                    latitude=latitude, longitude=longitude, delta=delta,
                    source=source, day_range=length, start_date=start.isoformat(),
                )
            except FirmsProviderError as error:
                if attempt == MAX_ATTEMPTS:
                    print(f"    GAP: {source} {start} +{length}d ({error})",
                          file=sys.stderr)
                    failures += 1
                    break
                delay = REQUEST_SPACING_SECONDS * 2 ** attempt
                sleep(delay)
                continue
            hotspots.extend(response["fire_satellite_data"]["hotspots"])
            sleep(REQUEST_SPACING_SECONDS)
            break

    return hotspots, failures


def stored_detections() -> dict[str, set]:
    """Which days each cell lit, according to observations we already hold.

    The live collector has been writing FIRMS rows all along, and for the days
    it covers that record is better than anything refetching can produce: it
    was captured from the near-real-time feed at the time, which is exactly the
    window the archive products have not caught up with yet.

    Free, offline, and authoritative for its span - so it is merged in rather
    than competed with.
    """
    with Session() as session:
        rows = session.execute(
            text(
                "SELECT DISTINCT cell_id, observed_at::date "
                "FROM observations WHERE source = 'firms'"
            )
        ).all()

    days: dict[str, set] = defaultdict(set)
    for cell_id, day in rows:
        days[cell_id].add(day.isoformat())
    return days


def tally(hotspots) -> tuple[dict[str, set], dict[str, int], dict[str, float], dict[str, dict]]:
    """Per cell: which days it lit, how many detections, its hottest pixel, and
    the signature fitted from its own overpasses.

    The signature is free here and nowhere else. This function already holds a
    year of every pixel the country produced; counting days throws all of it
    away but the date. Fitting the profile in the same pass costs no request
    and no second script - see detectors/fire/signature.py for what it buys.
    """
    days: dict[str, set] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    peak: dict[str, float] = {}

    for hotspot in hotspots:
        cell_id = cell_for(hotspot["latitude"], hotspot["longitude"])
        if cell_id is None:
            continue  # the bounding box overshoots the service area
        days[cell_id].add(hotspot["acquisition_date"])
        counts[cell_id] += 1
        frp = hotspot.get("frp")
        if frp is not None:
            peak[cell_id] = max(peak.get(cell_id, 0.0), float(frp))

    # Cut the history the way the live collector cuts it - one cell, one
    # overpass - so the fitted pixel count means what it will mean at scoring
    # time rather than a year's pixels in one number.
    samples: dict[str, list] = defaultdict(list)
    for (cell_id, moment), pixels in signature.overpasses(hotspots).items():
        features = signature.features_of(pixels, moment)
        if features is not None:
            samples[cell_id].append(features)

    profiles = {
        cell_id: profile
        for cell_id, cell_samples in samples.items()
        if (profile := signature.fit(cell_samples)) is not None
    }

    return days, counts, peak, profiles


# The signature columns, in one place so the row builder and the INSERT cannot
# drift apart. A cell with too few overpasses gets NULL across all of them,
# which is the honest answer and stays distinguishable from a fitted profile
# that happens to read low.
SIGNATURE_FIELDS = (
    "signature_samples", "hour_mean", "hour_concentration",
    "log_frp_mean", "log_frp_sd", "pixels_mean", "pixels_sd",
    "scatter_mean_m", "scatter_sd_m",
)


def signature_columns_exist() -> bool:
    """Whether this database has had the signature migration applied.

    The rate columns and the signature columns are independent answers to
    independent questions, and a database that has only the first must still
    be able to rebuild it. Tying the two together would mean a schema lag
    blocks the repair of an unrelated table.
    """
    with Session() as session:
        found = session.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'firms_baselines' "
                "AND column_name = 'signature_samples'"
            )
        ).scalar()
    return bool(found)


def _signature_row(profile: dict | None) -> dict:
    """A fitted profile as columns, or all-NULL when there was none."""
    if profile is None:
        return dict.fromkeys(SIGNATURE_FIELDS)
    return {
        "signature_samples": profile["samples"],
        "hour_mean": profile["hour_mean"],
        "hour_concentration": profile["hour_concentration"],
        "log_frp_mean": profile["log_frp_mean"],
        "log_frp_sd": profile["log_frp_sd"],
        "pixels_mean": profile["pixels_mean"],
        "pixels_sd": profile["pixels_sd"],
        "scatter_mean_m": profile["scatter_mean_m"],
        "scatter_sd_m": profile["scatter_sd_m"],
    }


def store(days, counts, peak, profiles, days_observed: int,
          window_start: date, window_end: date) -> int:
    """One row per service-area cell, zeros included."""
    # A database without the signature migration still gets its rate baseline
    # rebuilt; it just does not get the profiles. Better a table that suppresses
    # industrial sources without the finer judgement than no table at all.
    with_signatures = signature_columns_exist()
    if not with_signatures:
        print("  signature columns absent; writing rate baseline only "
              "(run: alembic upgrade firms_signatures)", file=sys.stderr)

    rows = [
        {
            "cell_id": cell.cell_id,
            "days_observed": days_observed,
            "detection_days": len(days.get(cell.cell_id, ())),
            "detections": counts.get(cell.cell_id, 0),
            "peak_frp_mw": peak.get(cell.cell_id),
            "window_start": window_start,
            "window_end": window_end,
            **(_signature_row(profiles.get(cell.cell_id)) if with_signatures else {}),
        }
        for cell in service_area_cells()
    ]

    columns = ("cell_id", "days_observed", "detection_days", "detections",
               "peak_frp_mw", "window_start", "window_end",
               *(SIGNATURE_FIELDS if with_signatures else ()))

    with Session() as session:
        session.execute(text("DELETE FROM firms_baselines"))
        session.execute(
            text(
                "INSERT INTO firms_baselines ({}) VALUES ({})".format(
                    ", ".join(columns),
                    ", ".join(f":{name}" for name in columns),
                )
            ),
            rows,
        )
        session.commit()
    return len(rows)


def build(days: int = DEFAULT_DAYS, agent: FirmsDataAgent | None = None) -> dict:
    """Measure how often each cell shows a hotspot anyway."""
    agent = agent or FirmsDataAgent()
    box = _service_area_box()
    today = datetime.now(timezone.utc).date()

    all_hotspots: list[dict] = []
    gaps = 0
    spans = windows(days, today)
    for index, (start, length) in enumerate(spans, 1):
        print(f"  [{index}/{len(spans)}] polar {start} +{length}d", file=sys.stderr)
        fetched, failures = fetch_window(agent, box, start, length, today)
        all_hotspots.extend(fetched)
        gaps += failures

    # The geostationary feed walks the same year in its own stride.
    geo_spans = windows(days, today, day_range=GEOSTATIONARY_DAY_RANGE)
    for index, (start, length) in enumerate(geo_spans, 1):
        if index % 20 == 1:
            print(f"  [{index}/{len(geo_spans)}] geostationary {start}", file=sys.stderr)
        fetched, failures = fetch_window(
            agent, box, start, length, today, sources=GEOSTATIONARY_SOURCES
        )
        all_hotspots.extend(fetched)
        gaps += failures

    # Refuse to write a baseline built from a fraction of the window.
    #
    # This is the one failure that must never be quiet. Every missing window
    # lowers some cell's detection count, which raises its rarity, which lets
    # an industrial site through as a fire - and the resulting table looks
    # perfectly well-formed. Two earlier runs of this script did exactly that:
    # they reported success, wrote 1,174 tidy rows, and the furnace we already
    # knew about scored 0.986 and would have opened an incident every night.
    #
    # An old baseline is better than a wrong one, so a bad run leaves the
    # existing table alone.
    attempted = (
        sum(len(sources_for(start, today)) for start, _ in spans)
        + len(geo_spans) * len(GEOSTATIONARY_SOURCES)
    )
    if attempted and gaps / attempted > MAX_GAP_SHARE:
        raise SystemExit(
            f"refusing to store: {gaps} of {attempted} source-windows failed "
            f"({gaps / attempted:.0%}, limit {MAX_GAP_SHARE:.0%}). "
            "A partial fetch makes cells look quieter than they are, which is "
            "the direction that lets an industrial site through. "
            "The existing baseline has been left untouched."
        )

    days_lit, counts, peak, profiles = tally(all_hotspots)

    # Merge what the collector already stored. A day either source saw is a day
    # the cell lit, so the union is the honest answer.
    merged_from_store = 0
    for cell_id, stored_days in stored_detections().items():
        before = len(days_lit.get(cell_id, ()))
        days_lit[cell_id] = days_lit.get(cell_id, set()) | stored_days
        merged_from_store += len(days_lit[cell_id]) - before

    written = store(
        days_lit, counts, peak, profiles, days,
        today - timedelta(days=days - 1), today,
    )

    lit = sum(1 for cell in days_lit if days_lit[cell])
    return {
        "hotspots": len(all_hotspots),
        "cells_written": written,
        "cells_ever_lit": lit,
        "days_observed": days,
        "gaps": gaps,
        "days_added_from_store": merged_from_store,
        "cells_profiled": len(profiles),
    }


def main() -> None:
    """Build the hotspot baselines from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    arguments = parser.parse_args()
    if arguments.days < 1:
        raise SystemExit("--days must be at least 1")

    summary = build(arguments.days)
    print(
        f"\n{summary['hotspots']:,} hotspots over {summary['days_observed']} days; "
        f"{summary['cells_written']:,} cells written, "
        f"{summary['cells_ever_lit']:,} of them have ever lit"
    )


if __name__ == "__main__":
    main()
