"""Build the weather climatology from Open-Meteo's historical archive.

This is what turns "different from last week" into "unusual for mid-September",
and it is a one-off backfill rather than something that accumulates: the archive
serves hourly reanalysis back to 1940, so a decade of context is available now
instead of in ten years' time.

    python -m scripts.build_weather_baselines
    python -m scripts.build_weather_baselines --years 5 --stride 3

What it does, per cell: pull every hour of the last ten complete calendar years,
sort those hours into 288 buckets by (month, hour-of-day), and reduce each
bucket to a distribution — mean, spread, median, MAD and five percentiles.

Three choices worth knowing:

  * Complete calendar years only, ending last December. A partial current year
    would weight recent months more heavily than old ones and quietly tilt
    every bucket it touched.
  * The coarse forecast subgrid, not all 1,174 cells. Climatology is a smooth
    regional field — the Negev and the Galilee differ, two adjacent 5 km cells
    do not — so ~15 km spacing captures it at an eighth of the fetch. The read
    side maps any cell to its nearest baseline cell.
  * Vapour pressure deficit is computed here rather than fetched, because the
    archive does not serve it and it is exactly derivable from temperature and
    humidity. It is the best single drying measure in the set, so it is worth
    the four lines.

A full run is about two minutes of provider time and 400 MB of transfer.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from typing import Any

import numpy as np
import requests
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import Table, MetaData

from ecoguard.collection.shared.open_meteo.forecast import forecast_cells
from ecoguard.database.engine import Session, engine

ARCHIVE_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"

# Fetched from the archive. Deliberately short: these four plus the one derived
# below are what an anomaly check actually asks about, and every extra variable
# multiplies a 400 MB download.
ARCHIVE_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "precipitation",
)
DERIVED_VARIABLES = ("vapour_pressure_deficit",)
VARIABLES = ARCHIVE_VARIABLES + DERIVED_VARIABLES

DEFAULT_YEARS = 10
# Smaller than it could be. The provider weighs a request by locations x days x
# variables, and fifty locations for a whole year is heavy enough that a run
# earns sustained 429s partway through. Twenty-five halves the weight of each
# call for the same total volume, and the run finishes instead of stalling.
LOCATIONS_PER_REQUEST = 25
TIMEOUT_SECONDS = 600

# Seconds between archive calls. One request here is 50 locations x 365 days x
# 4 variables, which the provider weighs heavily — thirty of them back to back
# earns a 429 partway through, which is how the first run of this script
# ended. Spacing them is the difference between a seven-minute job that
# finishes and a two-minute one that does not.
REQUEST_SPACING_SECONDS = 12.0
MAX_ATTEMPTS = 6

# A bucket with fewer samples than this is not a distribution, it is a rumour.
# Ten years of one month at one hour is about 300; anything an order of
# magnitude below that means the fetch was short and the bucket is dropped
# rather than stored with a confident-looking p95 behind five readings.
MIN_SAMPLES = 30


def saturation_vapour_pressure(temperature_c: np.ndarray) -> np.ndarray:
    """Tetens' equation, kPa. The denominator of relative humidity."""
    return 0.6108 * np.exp(17.27 * temperature_c / (temperature_c + 237.3))


def vapour_pressure_deficit(temperature_c, humidity_percent) -> np.ndarray:
    """How much more water the air could hold than it currently does, in kPa.

    The honest drying measure. Relative humidity alone is misleading across
    temperatures — 25% at 15 C and 25% at 35 C are wildly different demands on
    a fuel — and this collapses both into one number.
    """
    return saturation_vapour_pressure(temperature_c) * (1.0 - humidity_percent / 100.0)


def fetch(
    cells, start: date, end: date, session: Any, sleep=time.sleep
) -> list[dict[str, Any]]:
    """One archive call for a batch of cells over a date range.

    Retries on 429 and on server errors, backing off exponentially and
    honouring Retry-After when the provider sends one. A rate limit here is not
    a failure — it is the provider asking for a slower pace, and the only wrong
    response is to give up on a decade of history already half fetched.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = _request(cells, start, end, session)
        if response.status_code != 429 and response.status_code < 500:
            break
        if attempt == MAX_ATTEMPTS:
            response.raise_for_status()
        delay = _retry_after(response) or REQUEST_SPACING_SECONDS * 2 ** attempt
        print(
            f"    provider asked to slow down ({response.status_code}); "
            f"waiting {delay:.0f}s",
            file=sys.stderr,
        )
        sleep(delay)

    response.raise_for_status()
    payload = response.json()
    # The API returns a bare object for one location and a list for many.
    return payload if isinstance(payload, list) else [payload]


def _retry_after(response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _request(cells, start: date, end: date, session: Any):
    return session.get(
        ARCHIVE_ENDPOINT,
        params={
            "latitude": ",".join(str(cell.latitude) for cell in cells),
            "longitude": ",".join(str(cell.longitude) for cell in cells),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(ARCHIVE_VARIABLES),
            "timezone": "UTC",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        },
        timeout=TIMEOUT_SECONDS,
    )


def bucket_index(stamps: list[str]) -> np.ndarray:
    """Map each timestamp to its (month, hour) bucket, 0-287.

    Parsed by slicing rather than datetime.fromisoformat: the archive returns
    a fixed `YYYY-MM-DDTHH:MM` and there are 87,600 of them per cell-decade, so
    the string work is worth avoiding.
    """
    months = np.fromiter((int(s[5:7]) for s in stamps), dtype=np.int16, count=len(stamps))
    hours = np.fromiter((int(s[11:13]) for s in stamps), dtype=np.int16, count=len(stamps))
    return (months - 1) * 24 + hours


def summarise(values: np.ndarray) -> dict[str, float] | None:
    """Reduce one bucket's samples to the distribution we store."""
    clean = values[np.isfinite(values)]
    if clean.size < MIN_SAMPLES:
        return None
    median = float(np.median(clean))
    return {
        "samples": int(clean.size),
        "mean": float(clean.mean()),
        "std": float(clean.std()),
        "median": median,
        # Median absolute deviation. Survives the skew that makes a standard
        # deviation useless for precipitation and wind.
        "mad": float(np.median(np.abs(clean - median))),
        "p05": float(np.percentile(clean, 5)),
        "p25": float(np.percentile(clean, 25)),
        "p75": float(np.percentile(clean, 75)),
        "p95": float(np.percentile(clean, 95)),
        "minimum": float(clean.min()),
        "maximum": float(clean.max()),
    }


def rows_for_cell(cell_id: str, series: dict[str, np.ndarray], buckets: np.ndarray):
    """Every stored row for one cell: variable x month x hour.

    The hours are sorted into buckets once and reused for all five variables,
    because the time axis is identical across them and re-sorting per variable
    would be five times the work for the same answer.
    """
    order = np.argsort(buckets, kind="stable")
    edges = np.searchsorted(buckets[order], np.arange(289))

    for variable, values in series.items():
        ordered = values[order]
        for bucket in range(288):
            summary = summarise(ordered[edges[bucket]:edges[bucket + 1]])
            if summary is None:
                continue
            yield {
                "cell_id": cell_id,
                "variable": variable,
                "month": bucket // 24 + 1,
                "hour": bucket % 24,
                **summary,
            }


def already_built() -> set[str]:
    """Cells that already have baselines, so a resumed run skips them.

    A batch is only written once all of its years are fetched, so a rate limit
    partway through used to discard everything fetched for that batch. Skipping
    finished cells makes a failed run cost only the batch it died in, which
    matters when the whole job is twenty minutes of someone else's quota.
    """
    with Session() as session:
        return set(
            session.execute(
                text("SELECT DISTINCT cell_id FROM weather_baselines")
            ).scalars().all()
        )


def build(years: int, stride: int, cells=None, rebuild: bool = False) -> tuple[int, str]:
    cells = list(cells if cells is not None else forecast_cells(stride))
    if not rebuild:
        done = already_built()
        skipped = sum(1 for cell in cells if cell.cell_id in done)
        cells = [cell for cell in cells if cell.cell_id not in done]
        if skipped:
            print(f"  {skipped} cells already built, resuming with {len(cells)}", file=sys.stderr)
    if not cells:
        print("  nothing left to build", file=sys.stderr)
        return 0, "unchanged"

    # Complete calendar years only, ending last December.
    last_year = date.today().year - 1
    first_year = last_year - years + 1
    span = f"{first_year}-{last_year}"

    table = Table("weather_baselines", MetaData(), autoload_with=engine)
    http = requests.Session()
    written = 0

    for start in range(0, len(cells), LOCATIONS_PER_REQUEST):
        batch = cells[start:start + LOCATIONS_PER_REQUEST]
        collected: dict[str, dict[str, list[np.ndarray]]] = {
            cell.cell_id: {variable: [] for variable in VARIABLES} for cell in batch
        }
        stamps: list[str] = []

        for year in range(first_year, last_year + 1):
            print(
                f"  cells {start + 1}-{start + len(batch)} of {len(cells)}, {year}",
                end="\r", file=sys.stderr,
            )
            if written or year > first_year:
                time.sleep(REQUEST_SPACING_SECONDS)
            responses = fetch(batch, date(year, 1, 1), date(year, 12, 31), http)
            for cell, response in zip(batch, responses):
                hourly = response["hourly"]
                if cell is batch[0]:
                    stamps.extend(hourly["time"])
                raw = {
                    variable: np.array(hourly[variable], dtype=np.float32)
                    for variable in ARCHIVE_VARIABLES
                }
                raw["vapour_pressure_deficit"] = vapour_pressure_deficit(
                    raw["temperature_2m"], raw["relative_humidity_2m"]
                )
                for variable in VARIABLES:
                    collected[cell.cell_id][variable].append(raw[variable])

        buckets = bucket_index(stamps)
        for cell in batch:
            series = {
                variable: np.concatenate(parts)
                for variable, parts in collected[cell.cell_id].items()
            }
            rows = list(rows_for_cell(cell.cell_id, series, buckets))
            if not rows:
                continue
            with Session() as session:
                # Rebuilding with a different year span replaces rather than
                # duplicates, so a second run is a refresh and not a conflict.
                session.execute(
                    insert(table).values(rows).on_conflict_do_update(
                        index_elements=["cell_id", "variable", "month", "hour"],
                        set_={
                            column: getattr(insert(table).excluded, column)
                            for column in rows[0] if column not in
                            ("cell_id", "variable", "month", "hour")
                        },
                    )
                )
                session.commit()
            written += len(rows)

    return written, span


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS)
    parser.add_argument(
        "--rebuild", action="store_true",
        help="refetch cells that already have baselines instead of skipping them",
    )
    parser.add_argument(
        "--stride", type=int, default=3,
        help="use every Nth grid row and column (default 3, about 15 km)",
    )
    arguments = parser.parse_args()

    if arguments.years < 1 or arguments.stride < 1:
        raise SystemExit("--years and --stride must be at least 1")

    written, span = build(arguments.years, arguments.stride, rebuild=arguments.rebuild)
    print(f"\nWrote {written:,} baseline buckets from {span}")


if __name__ == "__main__":
    main()
