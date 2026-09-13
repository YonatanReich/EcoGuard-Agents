"""Load elevation, slope and land cover into the surface_cells table.

Why this is in the store at all: a fire's rate of spread is not a property of
the weather alone. The same wind and humidity produce a slow creep on a flat
plain of bare rock and a run through pine on a slope, because flames lean into
the ground ahead of them and preheat it, and because something has to burn. A
risk analyser that cannot see slope and fuel cannot tell those two fires apart,
so both have to be answerable from the store in the same round trip as
population and weather.

Two sources, one grid, one pass:

  * Copernicus DEM GLO-90 — a 90 m global surface model, free, unauthenticated.
    https://copernicus-dem-90m.s3.amazonaws.com/
  * ESA WorldCover 2021 v200 — 10 m land cover in eleven classes.
    https://esa-worldcover.s3.eu-central-1.amazonaws.com/

Both are already used by the historical feature builders in research/; this
brings them into Postgres on the grid the drawn-area summary reads.

Four deliberate choices:

  * Slope and aspect are computed on the *native 90 m* mosaic, before
    coarsening. Deriving them from an already-averaged surface would smooth
    away the gradient that is the whole point - a canyon averaged to 270 m is
    flat.
  * The DEM mosaic is built before the derivative, not tile by tile, so there
    is no seam: a 3x3 neighbourhood straddling two tiles is an ordinary read.
  * Land cover is stored as the *fraction* of each cell in each class, not as
    one dominant label. A 270 m cell holds some nine hundred WorldCover pixels
    and is almost never pure, and the mixture of scrub and houses is exactly
    the wildland-urban interface a single label would erase.
  * WorldCover is read in horizontal strips. The country at 10 m is a gigabyte
    of pixels, but it reduces to one number per class per cell, so only the
    strip needs to be in memory.

Run as a module, like the other scripts here:

    python -m scripts.load_surface_grid                # ~270 m cells
    python -m scripts.load_surface_grid --coarsen 1    # native 90 m

This is a full reload: surface_cells is emptied first. The ground does not
move, so this runs once and then only when a source publishes a new version.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.merge import merge
from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.database.repositories.surface import COVER_COLUMNS, bearing_degrees
from research.datasets.build_historical_landcover_terrain_features import (
    DEM_VERSION,
    LAND_COVER_CLASSES,
    WORLDCOVER_VERSION,
    StaticFeatureBuildError,
    dem_tile,
    download_file,
    worldcover_tile,
)
from ecoguard.shared.grid import (
    ISRAEL_RISK_BOUNDS,
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
)
from ecoguard.shared.service_area import DEFAULT_SERVICE_AREA_PATH, ServiceArea
from ecoguard.paths import GENERATED

# The same layout ecoguard/analyzers/emergency/fire/static_feature_store.py already reads, so the tiles
# are downloaded once and shared with the offline risk grid.
SOURCE_DIRECTORY = GENERATED / "static_environmental_sources"
DEM_SUBDIRECTORY = "copernicus_dem_glo90"
WORLDCOVER_SUBDIRECTORY = "worldcover_2021"

# Three GLO-90 pixels is about 270 m. Fine enough that a hillside is still a
# hillside, coarse enough that the country is a few hundred thousand rows
# rather than three million - the same order as population_cells, on a database
# the whole team shares. --coarsen 1 loads the native grid where that is worth
# the space.
DEFAULT_COARSEN = 3

# WorldCover is 1/12000 of a degree and GLO-90 is 1/1200, so one DEM pixel is
# exactly ten cover pixels across. Exactly, not approximately: it is what lets
# the two grids share cell boundaries instead of being resampled onto each
# other with a half-pixel of slop.
COVER_PER_DEM_PIXEL = 10

# Output rows per WorldCover read. Forty rows of 270 m cells is about 25 MB of
# 10 m pixels, which is the whole reason this is stripped at all.
STRIP_ROWS = 40

# Same batch size as the population loader, for the same reason: a few hundred
# round trips for a national grid, well inside psycopg's parameter limit.
CHUNK_SIZE = 5_000

# Below this the slope vectors in a block cancel out and the block faces no
# direction. Units are degrees of slope per pixel, so this is a hundredth of a
# degree of average tilt.
FLAT_EPSILON = 1e-2

# The WorldCover codes that get their own column, in the order they appear in
# COVER_COLUMNS. The last column, `unmapped`, has no code: it is the remainder,
# and carries nodata plus the three classes Israel has none of.
COVER_CODES = tuple(
    code for code, name in LAND_COVER_CLASSES.items() if name in COVER_COLUMNS
)

INSERT = text(
    f"""
    INSERT INTO surface_cells (
      cell, elevation_m, slope_deg, slope_max_deg, aspect_deg,
      {", ".join(COVER_COLUMNS)}
    )
    VALUES (
      ST_MakeEnvelope(:west, :south, :east, :north, 4326),
      :elevation_m, :slope_deg, :slope_max_deg, :aspect_deg,
      {", ".join(f":{column}" for column in COVER_COLUMNS)}
    )
    """
)


def required_dem_tiles(bounds: tuple[float, float, float, float]) -> list[tuple[str, str]]:
    """The GLO-90 tiles covering a bounding box, named by their SW corner."""
    west, south, east, north = bounds
    return sorted(
        {
            dem_tile(latitude, longitude)
            for latitude in range(math.floor(south), math.floor(north) + 1)
            for longitude in range(math.floor(west), math.floor(east) + 1)
        }
    )


def required_cover_tiles(bounds: tuple[float, float, float, float]) -> list[tuple[str, str]]:
    """The WorldCover tiles covering a bounding box. They are 3 degrees wide."""
    west, south, east, north = bounds
    return sorted(
        {
            worldcover_tile(latitude, longitude)
            for latitude in (south, north)
            for longitude in (west, east)
        }
        | {
            worldcover_tile(latitude, longitude)
            for latitude in range(math.floor(south), math.floor(north) + 1)
            for longitude in range(math.floor(west), math.floor(east) + 1)
        }
    )


def fetch(tiles, directory: Path) -> list[Path]:
    """Download what is missing; skip what the provider does not publish.

    A tile that is entirely sea does not exist — GLO-90 and WorldCover are both
    published over land only, and N33/E034 is open Mediterranean. That is a
    fact about the tile, not a failure to fetch it: leave the hole and let the
    service-area mask drop it. Anything other than a 404 is a genuine provider
    problem and still stops the load.
    """
    for number, (filename, url) in enumerate(tiles, 1):
        print(f"  tile {number}/{len(tiles)}: {filename}", file=sys.stderr)
        try:
            download_file(url, directory / filename)
        except StaticFeatureBuildError as error:
            if "404" not in str(error):
                raise
            print(f"    not published (open sea): {filename}", file=sys.stderr)
    return [path for path in (directory / filename for filename, _ in tiles) if path.exists()]


def slope_aspect(
    elevation: np.ndarray, x_metres: np.ndarray | float, y_metres: float
) -> tuple[np.ndarray, np.ndarray]:
    """Horn's 3x3 slope and aspect over a whole north-up array.

    The same estimator the per-point research builder uses, vectorised: the
    eight neighbours weighted 1-2-1 on each side, which is less noisy on a
    metre-quantised DEM than a plain central difference and is what GDAL,
    ArcGIS and every fire model's terrain input agree on.

    Edges are padded by repeating the border row and column. That reports the
    outermost ring of the mosaic as slightly flatter than it is; the outermost
    ring is the Mediterranean and Jordan, and the service-area mask drops it.

    Args:
        elevation: metres, north-up, row 0 northernmost. NaN marks no data and
            propagates into every cell whose neighbourhood touches it.
        x_metres: ground width of one pixel. Pass a column vector to vary it by
            row - longitude degrees shrink with latitude, by 4% across Israel.
        y_metres: ground height of one pixel.

    Returns:
        (slope, aspect) in degrees. Aspect is the compass bearing the ground
        faces - downhill, clockwise from north, the direction water runs off.
        Fire runs the opposite way, which is why callers report aspect + 180.
    """
    padded = np.pad(elevation, 1, mode="edge")
    north_west, north, north_east = padded[:-2, :-2], padded[:-2, 1:-1], padded[:-2, 2:]
    west, east = padded[1:-1, :-2], padded[1:-1, 2:]
    south_west, south, south_east = padded[2:, :-2], padded[2:, 1:-1], padded[2:, 2:]

    eastward = ((north_east + 2 * east + south_east) - (north_west + 2 * west + south_west)) / (
        8 * x_metres
    )
    northward = ((north_west + 2 * north + north_east) - (south_west + 2 * south + south_east)) / (
        8 * y_metres
    )

    slope = np.degrees(np.arctan(np.hypot(eastward, northward)))
    # Negated because the gradient points uphill and aspect is the downhill
    # bearing; arctan2(east, north) rather than the usual (y, x) because a
    # compass bearing runs clockwise from north, not anticlockwise from east.
    aspect = np.degrees(np.arctan2(-eastward, -northward)) % 360
    return slope, aspect


def _reduce(values: np.ndarray, starts: tuple[np.ndarray, np.ndarray], reducer=np.add):
    """Reduce each block; ragged groups at the raster's edge are included."""
    rows, columns = starts
    return reducer.reduceat(reducer.reduceat(values, rows, axis=0), columns, axis=1)


def terrain_blocks(elevation: np.ndarray, valid: np.ndarray, transform, coarsen: int) -> dict:
    """Per-cell elevation and slope statistics, reduced from the native DEM.

    Each statistic is reduced the way its own meaning requires:

      * elevation: mean, the cell's general height.
      * slope: mean *and* max. The mean says what the cell is like; the max
        says whether there is a steep face inside it, which is the part a fire
        accelerates on and the part an average erases.
      * aspect: a slope-weighted vector sum, left as its east and north
        components for the caller to resolve. Bearings do not average as
        numbers - 350 and 10 are both north and their mean is due south - and a
        flat pixel has a meaningless bearing that must not get an equal vote.
    """
    height, width = elevation.shape
    x_degrees, y_degrees = abs(transform.a), abs(transform.e)
    latitudes = transform.f + (np.arange(height) + 0.5) * transform.e
    x_metres = (
        x_degrees * LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * 1000 * np.cos(np.radians(latitudes))
    ).reshape(-1, 1)
    y_metres = y_degrees * LATITUDE_KM_PER_DEGREE * 1000

    slope, aspect = slope_aspect(elevation, x_metres, y_metres)
    # A pixel with no data has no slope either; drop both together so a cell's
    # mean is taken over exactly the pixels that contributed to it.
    valid = valid & np.isfinite(slope)

    starts = (np.arange(0, height, coarsen), np.arange(0, width, coarsen))

    def masked(values: np.ndarray, fill: float) -> np.ndarray:
        return np.where(valid, values, fill)

    radians = np.radians(aspect)
    return {
        "starts": starts,
        "count": _reduce(valid.astype("float64"), starts),
        "elevation": _reduce(masked(elevation, 0.0), starts),
        "slope": _reduce(masked(slope, 0.0), starts),
        "slope_max": _reduce(masked(slope, -1.0), starts, np.maximum),
        "aspect_east": _reduce(masked(slope * np.sin(radians), 0.0), starts),
        "aspect_north": _reduce(masked(slope * np.cos(radians), 0.0), starts),
    }


def cover_fractions(
    bounds: tuple[float, float, float, float], shape: tuple[int, int], coarsen: int, paths
) -> np.ndarray:
    """Fraction of every cell in each cover class, as (rows, columns, classes).

    Read in horizontal strips: the country at 10 m is a gigabyte of pixels, but
    it reduces to one number per class per cell, so only a strip has to be in
    memory at a time. The strip boundaries fall on cell boundaries and the cover
    grid is an exact ten-to-one refinement of the DEM grid, so no pixel is
    counted twice or dropped between strips.

    The last plane is the remainder — nodata, and the classes Israel has none
    of — so every cell's fractions sum to 1 and a hole is visible instead of
    quietly shrinking the total.
    """
    west, south, east, north = bounds
    rows, columns = shape
    block = coarsen * COVER_PER_DEM_PIXEL
    degrees_per_row = (north - south) / rows
    fractions = np.zeros((rows, columns, len(COVER_COLUMNS)), dtype="float32")

    datasets = [rasterio.open(path) for path in paths]
    try:
        for first in range(0, rows, STRIP_ROWS):
            last = min(first + STRIP_ROWS, rows)
            strip_north = north - first * degrees_per_row
            strip_south = north - last * degrees_per_row
            covering = [
                dataset
                for dataset in datasets
                if dataset.bounds.bottom < strip_north and dataset.bounds.top > strip_south
            ]
            if not covering:
                continue
            # nodata=0 rather than a class code: an unmapped pixel must land in
            # the remainder, never be counted as ground of some type.
            values, _ = merge(covering, bounds=(west, strip_south, east, strip_north), nodata=0)
            values = values[0]

            starts = (
                np.arange(0, values.shape[0], block),
                np.arange(0, values.shape[1], block),
            )
            total = _reduce(np.ones(values.shape, dtype="float32"), starts)
            for plane, code in enumerate(COVER_CODES):
                fractions[first:last, :, plane] = _reduce(
                    (values == code).astype("float32"), starts
                ) / total
            print(f"  cover rows {last:,}/{rows:,}", end="\r", file=sys.stderr)
    finally:
        for dataset in datasets:
            dataset.close()

    # Whatever is left over after the named classes. Clipped at zero because
    # float32 sums of nine hundred ones can land a hair above 1.
    fractions[:, :, -1] = np.clip(1.0 - fractions[:, :, :-1].sum(axis=2), 0.0, 1.0)
    return fractions


def surface_cells(terrain: dict, cover: np.ndarray, transform, coarsen: int, shape: tuple[int, int]):
    """Yield one insertable row per cell that has any ground in it."""
    height, width = shape
    row_starts, column_starts = terrain["starts"]
    count = terrain["count"]
    if cover.shape[:2] != count.shape:
        raise SystemExit(f"cover grid {cover.shape[:2]} does not match terrain grid {count.shape}")

    for row_block, column_block in zip(*np.nonzero(count)):
        top = int(row_starts[row_block])
        left = int(column_starts[column_block])
        pixels = count[row_block, column_block]
        east = terrain["aspect_east"][row_block, column_block]
        north = terrain["aspect_north"][row_block, column_block]
        yield {
            "west": transform.c + left * transform.a,
            "east": transform.c + min(left + coarsen, width) * transform.a,
            "north": transform.f + top * transform.e,
            "south": transform.f + min(top + coarsen, height) * transform.e,
            "elevation_m": float(terrain["elevation"][row_block, column_block] / pixels),
            "slope_deg": float(terrain["slope"][row_block, column_block] / pixels),
            "slope_max_deg": float(terrain["slope_max"][row_block, column_block]),
            "aspect_deg": (
                None
                if math.hypot(east, north) < FLAT_EPSILON * pixels
                else bearing_degrees(east, north)
            ),
            **{
                column: float(cover[row_block, column_block, plane])
                for plane, column in enumerate(COVER_COLUMNS)
            },
        }


def build_elevation(bounds, source_directory: Path):
    """Download the DEM tiles the bounds need and merge them into one array."""
    print("Copernicus DEM GLO-90", file=sys.stderr)
    paths = fetch(required_dem_tiles(bounds), source_directory / DEM_SUBDIRECTORY)
    if not paths:
        raise SystemExit(f"no DEM tiles available for bounds {bounds}")

    datasets = [rasterio.open(path) for path in paths]
    try:
        # nodata=nan so a gap between tiles reads as "unknown" rather than as
        # sea level, which would invent a cliff along every missing edge.
        array, output_transform = merge(datasets, bounds=bounds, nodata=np.nan)
    finally:
        for dataset in datasets:
            dataset.close()
    return array[0].astype("float32"), output_transform


def load(
    bounds: tuple[float, float, float, float],
    coarsen: int,
    source_directory: Path,
    service_area_path: Path,
) -> tuple[int, dict[str, float]]:
    elevation, transform = build_elevation(bounds, source_directory)
    land = geometry_mask(
        [ServiceArea(service_area_path).geometry],
        out_shape=elevation.shape,
        transform=transform,
        invert=True,
    )
    terrain = terrain_blocks(elevation, land & np.isfinite(elevation), transform, coarsen)

    print(f"\n{WORLDCOVER_VERSION}", file=sys.stderr)
    cover_paths = fetch(
        required_cover_tiles(bounds), source_directory / WORLDCOVER_SUBDIRECTORY
    )
    if not cover_paths:
        raise SystemExit(f"no WorldCover tiles available for bounds {bounds}")
    cover = cover_fractions(bounds, terrain["count"].shape, coarsen, cover_paths)

    written = 0
    highest, steepest, lowest = -math.inf, 0.0, math.inf
    burnable = 0.0
    chunk: list[dict] = []

    with Session() as session:
        session.execute(text("TRUNCATE surface_cells"))
        for cell in surface_cells(terrain, cover, transform, coarsen, elevation.shape):
            chunk.append(cell)
            highest = max(highest, cell["elevation_m"])
            lowest = min(lowest, cell["elevation_m"])
            steepest = max(steepest, cell["slope_max_deg"])
            burnable += (
                cell["tree_cover"] + cell["shrubland"] + cell["grassland"] + cell["cropland"]
            )
            if len(chunk) >= CHUNK_SIZE:
                session.execute(INSERT, chunk)
                written += len(chunk)
                chunk = []
                print(f"  {written:,} cells...", end="\r", file=sys.stderr)
        if chunk:
            session.execute(INSERT, chunk)
            written += len(chunk)
        session.commit()

    return written, {
        "lowest_m": lowest,
        "highest_m": highest,
        "steepest_deg": steepest,
        "burnable_share": burnable / written if written else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coarsen",
        type=int,
        default=DEFAULT_COARSEN,
        help=f"merge N x N DEM pixels into one cell (default {DEFAULT_COARSEN}, about 270 m)",
    )
    parser.add_argument("--source-directory", type=Path, default=SOURCE_DIRECTORY)
    parser.add_argument("--service-area", type=Path, default=DEFAULT_SERVICE_AREA_PATH)
    arguments = parser.parse_args()

    if arguments.coarsen < 1:
        raise SystemExit("--coarsen must be at least 1")

    written, extremes = load(
        ISRAEL_RISK_BOUNDS, arguments.coarsen, arguments.source_directory, arguments.service_area
    )
    # The summary is the sanity check, the way the national total is for the
    # population loader. Expect about -430 m at the Dead Sea shore and roughly
    # 2,300 m on Hermon — not Mount Meron's 1,208 m, because the service-area
    # polygon includes the Golan — and a burnable share somewhere near half,
    # since more than a third of the country is Negev desert. Numbers far
    # outside that mean the wrong tiles or a broken mask, and they say so at a
    # glance.
    print(
        f"\nLoaded {written:,} cells from {DEM_VERSION} and {WORLDCOVER_VERSION}"
        f"\n  elevation {extremes['lowest_m']:.0f} m to {extremes['highest_m']:.0f} m,"
        f" steepest cell {extremes['steepest_deg']:.1f} deg"
        f"\n  burnable vegetation {extremes['burnable_share']:.1%} of the average cell"
    )


if __name__ == "__main__":
    main()
