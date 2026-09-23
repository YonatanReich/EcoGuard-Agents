"""Add static elevation, seasonal context, and prior-FIRMS density features."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import requests

from ecoguard.analyzers.fire.ml.build_historical_fire_negative_samples import (
    FIRMS_INPUT,
    FirmsIncident,
    haversine_km,
    load_firms_incidents,
    parse_timestamp,
)
from ecoguard.paths import GENERATED


INPUT_PATH = GENERATED / "fire_prediction_ml_dataset_2023_2026.csv"
OUTPUT_PATH = GENERATED / "fire_prediction_ml_environmental_dataset_2023_2026.csv"
ELEVATION_CACHE = GENERATED / "historical_environmental_elevation_cache.json"
ELEVATION_ENDPOINT = "https://api.open-meteo.com/v1/elevation"
USER_AGENT = "EcoGuard-Agents historical-environmental-builder/1.0"
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4
BATCH_SIZE = 100
ELEVATION_BATCH_PAUSE_SECONDS = 12.0
GRID_DEGREES = 0.1

SEASON_FEATURES = ("sin_day_of_year", "cos_day_of_year", "sin_hour", "cos_hour")
TOPOGRAPHY_FEATURES = ("elevation_m",)
FIRE_HISTORY_FEATURES = (
    "fires_within_5km_previous_30d",
    "fires_within_10km_previous_90d",
    "fires_within_25km_previous_365d",
    "days_since_previous_firms_candidate_within_10km",
)
ENVIRONMENTAL_FEATURES = SEASON_FEATURES + TOPOGRAPHY_FEATURES + FIRE_HISTORY_FEATURES
STATUS_FIELDS = ("elevation_collection_status", "land_cover_collection_status", "historical_fwi_collection_status")


class EnvironmentalBuildError(RuntimeError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_rows(path: Path = INPUT_PATH) -> list[dict[str, str]]:
    if not path.exists():
        raise EnvironmentalBuildError(f"input is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"sample_id", "timestamp", "latitude", "longitude", "fire_label"}
    if not rows or not required.issubset(rows[0]):
        raise EnvironmentalBuildError("input schema is incompatible")
    return sorted(rows, key=lambda row: (row["timestamp"], row["sample_id"]))


def coordinate_key(latitude: object, longitude: object) -> str:
    return f"{float(latitude):.6f},{float(longitude):.6f}"


def load_elevation_cache(path: Path = ELEVATION_CACHE) -> dict[str, float | None]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise EnvironmentalBuildError("elevation cache is corrupted") from None
    if value.get("source") != "Open-Meteo Elevation API / Copernicus DEM GLO-90" or not isinstance(value.get("values"), dict):
        raise EnvironmentalBuildError("elevation cache is incompatible")
    return value["values"]


def collect_elevations(
    rows: list[Mapping[str, Any]],
    *,
    cache_path: Path = ELEVATION_CACHE,
    session: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
    logger: Callable[[str], None] = print,
) -> dict[str, float | None]:
    cache = load_elevation_cache(cache_path)
    coordinates = {}
    for row in rows:
        coordinates[coordinate_key(row["latitude"], row["longitude"])] = (float(row["latitude"]), float(row["longitude"]))
    missing = [key for key in sorted(coordinates) if key not in cache]
    client = session or requests.Session()
    batches = [missing[index:index + BATCH_SIZE] for index in range(0, len(missing), BATCH_SIZE)]
    for batch_number, keys in enumerate(batches, start=1):
        latitudes = ",".join(str(coordinates[key][0]) for key in keys)
        longitudes = ",".join(str(coordinates[key][1]) for key in keys)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = client.get(
                    ELEVATION_ENDPOINT,
                    params={"latitude": latitudes, "longitude": longitudes},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    timeout=TIMEOUT_SECONDS,
                )
                if response.status_code >= 400:
                    if response.status_code == 429:
                        if attempt == MAX_ATTEMPTS:
                            raise EnvironmentalBuildError("elevation provider rate limit")
                        sleep(60.0)
                        continue
                    if response.status_code >= 500:
                        raise requests.RequestException("transient provider error")
                    raise EnvironmentalBuildError("elevation provider rejected the request")
                data = response.json()
                elevations = data.get("elevation") if isinstance(data, dict) else None
                if not isinstance(elevations, list) or len(elevations) != len(keys):
                    raise EnvironmentalBuildError("elevation provider returned malformed data")
                for key, elevation in zip(keys, elevations):
                    cache[key] = float(elevation) if elevation is not None else None
                _atomic_json(cache_path, {"source": "Open-Meteo Elevation API / Copernicus DEM GLO-90", "resolution_m": 90, "values": cache})
                break
            except (requests.Timeout, requests.RequestException):
                if attempt == MAX_ATTEMPTS:
                    raise EnvironmentalBuildError("elevation provider network failure") from None
                sleep(2 ** (attempt - 1))
        logger(f"Elevation progress: {batch_number}/{len(batches)} batches; cached={len(cache)}/{len(coordinates)}")
        if batch_number < len(batches):
            sleep(ELEVATION_BATCH_PAUSE_SECONDS)
    return cache


class PriorFirmsIndex:
    def __init__(self, incidents: Iterable[FirmsIncident]):
        self.cells: dict[tuple[int, int], list[FirmsIncident]] = {}
        for incident in incidents:
            cell = (math.floor(incident.longitude / GRID_DEGREES), math.floor(incident.latitude / GRID_DEGREES))
            self.cells.setdefault(cell, []).append(incident)
        for values in self.cells.values():
            values.sort(key=lambda incident: (incident.start, incident.candidate_id))

    def nearby(self, latitude: float, longitude: float, radius_km: float) -> Iterable[FirmsIncident]:
        x = math.floor(longitude / GRID_DEGREES)
        y = math.floor(latitude / GRID_DEGREES)
        radius = math.ceil(radius_km / (GRID_DEGREES * 90)) + 1
        for cell_x in range(x - radius, x + radius + 1):
            for cell_y in range(y - radius, y + radius + 1):
                yield from self.cells.get((cell_x, cell_y), ())


def historical_fire_features(
    index: PriorFirmsIndex,
    latitude: float,
    longitude: float,
    timestamp,
    *,
    excluded_candidate_ids: Iterable[str] = (),
) -> dict[str, Any]:
    excluded = set(excluded_candidate_ids)
    nearby = []
    for incident in index.nearby(latitude, longitude, 25.0):
        if incident.candidate_id in excluded:
            continue
        if incident.start >= timestamp:
            continue
        distance = haversine_km(latitude, longitude, incident.latitude, incident.longitude)
        if distance <= 25:
            nearby.append((incident, distance))
    def count(radius: float, days: int) -> int:
        cutoff = timestamp - timedelta(days=days)
        return sum(incident.start >= cutoff and distance <= radius for incident, distance in nearby)
    previous_10 = [incident for incident, distance in nearby if distance <= 10]
    days_since = (
        min((timestamp - incident.start).total_seconds() / 86400 for incident in previous_10)
        if previous_10 else None
    )
    return {
        "fires_within_5km_previous_30d": count(5, 30),
        "fires_within_10km_previous_90d": count(10, 90),
        "fires_within_25km_previous_365d": count(25, 365),
        "days_since_previous_firms_candidate_within_10km": round(days_since, 6) if days_since is not None else None,
    }


def enrich_rows(rows: list[Mapping[str, Any]], incidents: Iterable[FirmsIncident], elevations: Mapping[str, float | None]) -> list[dict[str, Any]]:
    index = PriorFirmsIndex(incidents)
    output = []
    for row in rows:
        timestamp = parse_timestamp(row["timestamp"])
        latitude, longitude = float(row["latitude"]), float(row["longitude"])
        day = timestamp.timetuple().tm_yday
        enriched = dict(row)
        enriched.update({
            "sin_day_of_year": math.sin(2 * math.pi * day / 365.25),
            "cos_day_of_year": math.cos(2 * math.pi * day / 365.25),
            "sin_hour": math.sin(2 * math.pi * timestamp.hour / 24),
            "cos_hour": math.cos(2 * math.pi * timestamp.hour / 24),
        })
        elevation = elevations.get(coordinate_key(latitude, longitude))
        enriched["elevation_m"] = elevation
        enriched["elevation_collection_status"] = "success" if elevation is not None else "unavailable"
        enriched["land_cover_collection_status"] = "not_collected_no_local_authoritative_cache"
        enriched["historical_fwi_collection_status"] = "not_available_from_current_source"
        enriched.update(historical_fire_features(index, latitude, longitude, timestamp))
        output.append(enriched)
    return output


def write_output(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fields = tuple(rows[0])
    temporary = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists(): temporary.unlink()


def build_environmental_dataset(*, input_path: Path = INPUT_PATH, firms_path: Path = FIRMS_INPUT, output_path: Path = OUTPUT_PATH, cache_path: Path = ELEVATION_CACHE, session: Any | None = None, logger: Callable[[str], None] = print) -> list[dict[str, Any]]:
    rows = load_rows(input_path)
    elevations = collect_elevations(rows, cache_path=cache_path, session=session, logger=logger)
    output = enrich_rows(rows, load_firms_incidents(firms_path), elevations)
    if len(output) != len(rows):
        raise EnvironmentalBuildError("row preservation failed")
    write_output(output_path, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--firms", type=Path, default=FIRMS_INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--elevation-cache", type=Path, default=ELEVATION_CACHE)
    args = parser.parse_args()
    try:
        rows = build_environmental_dataset(input_path=args.input, firms_path=args.firms, output_path=args.output, cache_path=args.elevation_cache)
    except EnvironmentalBuildError as error:
        print(f"Environmental build failed: {error}"); return 1
    print(f"Environmental rows: {len(rows)}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
