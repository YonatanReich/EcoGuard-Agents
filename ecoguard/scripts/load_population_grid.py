"""Loading a population raster into the database.

Stored per grid cell so an area drawn on the map can be answered by summing
what falls inside it, with a partly covered cell contributing its share."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from sqlalchemy import text

from ecoguard.database.engine import Session

# Rows per INSERT. Large enough that a 100 m national grid is a few hundred
# round trips, small enough to stay well inside psycopg's parameter limits.
CHUNK_SIZE = 5_000

INSERT = text(
    """
    INSERT INTO population_cells (cell, population)
    VALUES (ST_MakeEnvelope(:west, :south, :east, :north, 4326), :population)
    """
)


def cells_from_raster(path: Path, coarsen: int):
    """Yield {west, south, east, north, population} for every populated cell.

    Read one strip of `coarsen` rows at a time and reduce it to one value per
    output cell, so memory stays at a few rows regardless of raster size. The
    reduction is a *sum*: merging four 100 m pixels into one 200 m cell adds
    their people together, it does not average them.
    """
    with rasterio.open(path) as raster:
        if raster.count != 1:
            raise SystemExit(f"{path} has {raster.count} bands; expected a single count band")
        if raster.crs is None or raster.crs.to_epsg() != 4326:
            raise SystemExit(f"{path} is in {raster.crs}; expected EPSG:4326")

        transform = raster.transform
        # A rotated or sheared grid would make ST_MakeEnvelope wrong rather
        # than merely imprecise, so it is refused instead of approximated.
        if transform.b != 0 or transform.d != 0:
            raise SystemExit(f"{path} is not north-up; rotated rasters are not supported")

        def x_of(column: int) -> float:
            """The longitude of one raster column."""
            return transform.c + column * transform.a

        def y_of(row: int) -> float:
            """The latitude of one raster row."""
            return transform.f + row * transform.e

        column_starts = np.arange(0, raster.width, coarsen)

        for top in range(0, raster.height, coarsen):
            rows = min(coarsen, raster.height - top)
            strip = raster.read(
                1, window=Window(0, top, raster.width, rows), masked=True
            ).filled(0.0)
            # WorldPop marks empty land with a large negative nodata value, and
            # some tiles carry NaN. Both are "no people here", not a reading.
            strip = np.where(np.isfinite(strip) & (strip > 0), strip, 0.0)
            if not strip.any():
                continue

            # reduceat sums each group of `coarsen` columns and handles a
            # ragged final group at the raster's edge without padding.
            totals = np.add.reduceat(strip.sum(axis=0), column_starts)

            north, south = y_of(top), y_of(top + rows)
            for group in np.nonzero(totals)[0]:
                left = int(column_starts[group])
                right = min(left + coarsen, raster.width)
                yield {
                    "west": x_of(left),
                    "south": south,
                    "east": x_of(right),
                    "north": north,
                    "population": float(totals[group]),
                }


def load(path: Path, coarsen: int) -> tuple[int, float]:
    """Load a population raster into the database."""
    written = 0
    total = 0.0
    chunk: list[dict] = []

    with Session() as session:
        session.execute(text("TRUNCATE population_cells"))
        for cell in cells_from_raster(path, coarsen):
            chunk.append(cell)
            total += cell["population"]
            if len(chunk) >= CHUNK_SIZE:
                session.execute(INSERT, chunk)
                written += len(chunk)
                chunk = []
                print(f"  {written:,} cells…", end="\r", file=sys.stderr)
        if chunk:
            session.execute(INSERT, chunk)
            written += len(chunk)
        session.commit()

    return written, total


def main() -> None:
    """Load the population grid from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raster", type=Path, help="single-band EPSG:4326 population count GeoTIFF")
    parser.add_argument(
        "--coarsen",
        type=int,
        default=1,
        help="merge N x N source pixels into one cell (default 1, i.e. native resolution)",
    )
    arguments = parser.parse_args()

    if arguments.coarsen < 1:
        raise SystemExit("--coarsen must be at least 1")
    if not arguments.raster.exists():
        raise SystemExit(f"{arguments.raster} does not exist")

    written, total = load(arguments.raster, arguments.coarsen)
    # The total is the sanity check: against Israel's ~9.8 million it says at a
    # glance whether the right raster was loaded and whether nodata leaked in.
    print(f"\nLoaded {written:,} cells, {total:,.0f} people total")


if __name__ == "__main__":
    main()
