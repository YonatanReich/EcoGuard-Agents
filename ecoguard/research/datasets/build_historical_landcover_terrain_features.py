"""Add cached ESA WorldCover classes and DEM-neighborhood slope features."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import requests
from rasterio.windows import Window

from ecoguard.research.datasets.build_historical_environmental_features import coordinate_key
from ecoguard.paths import GENERATED


INPUT_PATH = GENERATED / "fire_prediction_ml_environmental_dataset_2023_2026.csv"
OUTPUT_PATH = GENERATED / "fire_prediction_ml_landcover_terrain_dataset_2023_2026.csv"
SOURCE_DIRECTORY = GENERATED / "static_environmental_sources"
CACHE_PATH = GENERATED / "historical_landcover_terrain_cache.json"
TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 4
USER_AGENT = "EcoGuard-Agents historical-static-environmental-builder/1.0"

WORLDCOVER_VERSION = "ESA WorldCover 2021 v200"
WORLDCOVER_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
DEM_VERSION = "Copernicus DEM GLO-90"
DEM_BASE = "https://copernicus-dem-90m.s3.amazonaws.com"

LAND_COVER_CLASSES = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse_vegetation",
    70: "snow_ice",
    80: "permanent_water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}
LAND_COVER_FEATURES = tuple(f"land_cover_{name}" for name in LAND_COVER_CLASSES.values())
TERRAIN_FEATURES = ("slope_degrees",)
STATIC_FEATURES = LAND_COVER_FEATURES + TERRAIN_FEATURES
CACHE_SCHEMA = 1


class StaticFeatureBuildError(RuntimeError):
    pass


def _hemisphere(value: int, positive: str, negative: str, width: int) -> str:
    return f"{positive if value >= 0 else negative}{abs(value):0{width}d}"


def worldcover_tile(latitude: float, longitude: float) -> tuple[str, str]:
    south = math.floor(latitude / 3) * 3
    west = math.floor(longitude / 3) * 3
    tile = f"{_hemisphere(south, 'N', 'S', 2)}{_hemisphere(west, 'E', 'W', 3)}"
    filename = f"ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
    return filename, f"{WORLDCOVER_BASE}/{filename}"


def dem_tile(latitude: float, longitude: float) -> tuple[str, str]:
    south, west = math.floor(latitude), math.floor(longitude)
    tile = f"{_hemisphere(south, 'N', 'S', 2)}_00_{_hemisphere(west, 'E', 'W', 3)}_00"
    stem = f"Copernicus_DSM_COG_30_{tile}_DEM"
    return f"{stem}.tif", f"{DEM_BASE}/{stem}/{stem}.tif"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def download_file(
    url: str,
    path: Path,
    *,
    session: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    if path.exists() and path.stat().st_size:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    client = session or requests.Session()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "image/tiff"},
                timeout=TIMEOUT_SECONDS,
                stream=True,
            )
            if response.status_code in {401, 403, 404}:
                raise StaticFeatureBuildError(f"static provider permanent HTTP {response.status_code}")
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.RequestException(f"transient HTTP {response.status_code}")
            if response.status_code >= 400:
                raise StaticFeatureBuildError(f"static provider HTTP {response.status_code}")
            digest = hashlib.sha256()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        handle.write(chunk); digest.update(chunk)
            if not temporary.stat().st_size:
                raise requests.RequestException("empty provider response")
            temporary.replace(path)
            return
        except (requests.Timeout, requests.RequestException):
            if temporary.exists(): temporary.unlink()
            if attempt == MAX_ATTEMPTS:
                raise StaticFeatureBuildError("static provider network failure") from None
            sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")


def slope_from_neighborhood(values: np.ndarray, cell_x_metres: float, cell_y_metres: float) -> float | None:
    values = np.asarray(values, dtype=float)
    if values.shape != (3, 3) or not np.isfinite(values).all() or cell_x_metres <= 0 or cell_y_metres <= 0:
        return None
    dz_dx = ((values[0, 2] + 2 * values[1, 2] + values[2, 2]) - (values[0, 0] + 2 * values[1, 0] + values[2, 0])) / (8 * cell_x_metres)
    dz_dy = ((values[2, 0] + 2 * values[2, 1] + values[2, 2]) - (values[0, 0] + 2 * values[0, 1] + values[0, 2])) / (8 * cell_y_metres)
    return round(math.degrees(math.atan(math.hypot(dz_dx, dz_dy))), 6)


def sample_land_cover(dataset: Any, latitude: float, longitude: float) -> int | None:
    try:
        row, column = dataset.index(longitude, latitude)
        value = int(dataset.read(1, window=Window(column, row, 1, 1))[0, 0])
    except (IndexError, ValueError):
        return None
    return value if value in LAND_COVER_CLASSES else None


def sample_slope(dataset: Any, latitude: float, longitude: float) -> float | None:
    try:
        row, column = dataset.index(longitude, latitude)
        values = dataset.read(1, window=Window(column - 1, row - 1, 3, 3), boundless=True, fill_value=np.nan)
    except (IndexError, ValueError):
        return None
    x_degrees, y_degrees = abs(dataset.transform.a), abs(dataset.transform.e)
    x_metres = x_degrees * 111_320 * math.cos(math.radians(latitude))
    y_metres = y_degrees * 110_574
    return slope_from_neighborhood(values, x_metres, y_metres)


def sample_slope_across_tiles(latitude: float, longitude: float, dataset_for: Callable[[float, float], Any]) -> float | None:
    """Apply the same 3x3 Horn calculation while resolving tile-edge cells."""
    step = 1 / 1200  # GLO-90 is three arc-seconds at this latitude.
    values = np.empty((3, 3), dtype=float)
    for row, latitude_offset in enumerate((step, 0.0, -step)):
        for column, longitude_offset in enumerate((-step, 0.0, step)):
            sample_latitude, sample_longitude = latitude + latitude_offset, longitude + longitude_offset
            dataset = dataset_for(sample_latitude, sample_longitude)
            try:
                raster_row, raster_column = dataset.index(sample_longitude, sample_latitude)
                values[row, column] = float(dataset.read(1, window=Window(raster_column, raster_row, 1, 1))[0, 0])
            except (IndexError, ValueError):
                values[row, column] = np.nan
    x_metres = step * 111_320 * math.cos(math.radians(latitude))
    y_metres = step * 110_574
    return slope_from_neighborhood(values, x_metres, y_metres)


def load_cache(path: Path = CACHE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists(): return {}
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): raise StaticFeatureBuildError("static feature cache is corrupted") from None
    if value.get("schema") != CACHE_SCHEMA or value.get("worldcover") != WORLDCOVER_VERSION or value.get("dem") != DEM_VERSION or not isinstance(value.get("values"), dict):
        raise StaticFeatureBuildError("static feature cache is incompatible")
    return value["values"]


def collect_static_features(
    rows: list[Mapping[str, Any]], *, source_directory: Path = SOURCE_DIRECTORY,
    cache_path: Path = CACHE_PATH, session: Any | None = None,
    sleep: Callable[[float], None] = time.sleep, logger: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    coordinates = {coordinate_key(row["latitude"], row["longitude"]): (float(row["latitude"]), float(row["longitude"])) for row in rows}
    cache = load_cache(cache_path)
    missing = [key for key in sorted(coordinates) if key not in cache or cache[key].get("slope_degrees") is None]
    required_worldcover = {worldcover_tile(*coordinates[key]) for key in missing}
    step = 1 / 1200
    required_dem = {
        dem_tile(coordinates[key][0] + latitude_offset, coordinates[key][1] + longitude_offset)
        for key in missing
        for latitude_offset in (step, 0.0, -step)
        for longitude_offset in (-step, 0.0, step)
    }
    for number, (filename, url) in enumerate(sorted(required_worldcover), 1):
        logger(f"WorldCover tile {number}/{len(required_worldcover)}: {filename}")
        download_file(url, source_directory / "worldcover_2021" / filename, session=session, sleep=sleep)
    for number, (filename, url) in enumerate(sorted(required_dem), 1):
        logger(f"DEM tile {number}/{len(required_dem)}: {filename}")
        download_file(url, source_directory / "copernicus_dem_glo90" / filename, session=session, sleep=sleep)
    land_datasets: dict[str, Any] = {}; dem_datasets: dict[str, Any] = {}
    try:
        for number, key in enumerate(missing, 1):
            latitude, longitude = coordinates[key]
            land_filename, _ = worldcover_tile(latitude, longitude)
            dem_filename, _ = dem_tile(latitude, longitude)
            if land_filename not in land_datasets:
                land_datasets[land_filename] = rasterio.open(source_directory / "worldcover_2021" / land_filename)
            def dataset_for(sample_latitude: float, sample_longitude: float):
                # GLO-90 COG bounds are pixel-centre shifted by half a cell, so
                # an integer-degree coordinate can belong to the adjacent tile.
                for latitude_shift in (0.0, -0.5, 0.5):
                    for longitude_shift in (0.0, -0.5, 0.5):
                        filename, _ = dem_tile(sample_latitude + latitude_shift, sample_longitude + longitude_shift)
                        path = source_directory / "copernicus_dem_glo90" / filename
                        if not path.exists(): continue
                        if filename not in dem_datasets: dem_datasets[filename] = rasterio.open(path)
                        dataset = dem_datasets[filename]
                        if dataset.bounds.left <= sample_longitude < dataset.bounds.right and dataset.bounds.bottom <= sample_latitude < dataset.bounds.top:
                            return dataset
                raise StaticFeatureBuildError("DEM neighborhood cell is outside cached tile coverage")
            land = land_datasets[land_filename]
            code = sample_land_cover(land, latitude, longitude)
            cache[key] = {"land_cover_code": code, "land_cover_class": LAND_COVER_CLASSES.get(code), "slope_degrees": sample_slope_across_tiles(latitude, longitude, dataset_for)}
            if number % 100 == 0 or number == len(missing):
                _atomic_json(cache_path, {"schema": CACHE_SCHEMA, "worldcover": WORLDCOVER_VERSION, "dem": DEM_VERSION, "values": cache})
                logger(f"Static feature progress: {number}/{len(missing)} misses; cache={len(cache)}/{len(coordinates)}")
    finally:
        for dataset in (*land_datasets.values(), *dem_datasets.values()): dataset.close()
    return cache


def enrich_rows(rows: list[Mapping[str, Any]], cache: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        enriched = dict(row); value = cache.get(coordinate_key(row["latitude"], row["longitude"]), {})
        code, slope = value.get("land_cover_code"), value.get("slope_degrees")
        enriched.update({"land_cover_source_code": code, "land_cover_source_class": value.get("land_cover_class"), "land_cover_static_status": "success" if code in LAND_COVER_CLASSES else "unavailable", "slope_degrees": slope, "terrain_slope_status": "success" if slope is not None else "unavailable"})
        for class_code, class_name in LAND_COVER_CLASSES.items(): enriched[f"land_cover_{class_name}"] = int(code == class_code)
        output.append(enriched)
    return output


def write_output(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists(): temporary.unlink()


def build_dataset(*, input_path: Path = INPUT_PATH, output_path: Path = OUTPUT_PATH, source_directory: Path = SOURCE_DIRECTORY, cache_path: Path = CACHE_PATH, session: Any | None = None, logger: Callable[[str], None] = print) -> list[dict[str, Any]]:
    with input_path.open(encoding="utf-8-sig", newline="") as handle: rows = list(csv.DictReader(handle))
    if not rows: raise StaticFeatureBuildError("environmental input is empty or missing")
    cache = collect_static_features(rows, source_directory=source_directory, cache_path=cache_path, session=session, logger=logger)
    output = enrich_rows(rows, cache)
    if len(output) != len(rows): raise StaticFeatureBuildError("row preservation failed")
    write_output(output_path, output); return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH); parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--source-directory", type=Path, default=SOURCE_DIRECTORY); parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    args = parser.parse_args()
    try: rows = build_dataset(input_path=args.input, output_path=args.output, source_directory=args.source_directory, cache_path=args.cache)
    except (StaticFeatureBuildError, OSError, rasterio.errors.RasterioError) as error:
        print(f"Static environmental build failed: {error}"); return 1
    print(f"Land-cover/terrain rows: {len(rows)}"); return 0


if __name__ == "__main__": raise SystemExit(main())
