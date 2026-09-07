"""Build deterministic FIRMS-excluded proxy-negative wildfire samples."""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import math
import random
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from research.datasets.build_firms_fire_rescue_ground_truth import (
    BOUNDARY_CACHE,
    FIRE_RESCUE_RECORDS,
    SettlementSpatialIndex,
    build_official_index,
    load_boundary_geojson,
    load_csv,
    settlement_polygons,
)


POSITIVE_INPUT = Path("data/generated/historical_fire_weather_features_2023_2026.csv")
FIRMS_INPUT = Path("data/generated/firms_israel_candidate_incidents_2023_2026.csv")
OUTPUT_PATH = Path("data/generated/historical_fire_negative_samples_2023_2026.csv")

DEFAULT_NEGATIVES_PER_POSITIVE = 2
DEFAULT_SPATIAL_EXCLUSION_KM = 5.0
DEFAULT_TEMPORAL_EXCLUSION_HOURS = 72.0
DEFAULT_RANDOM_SEED = 20260827
DEFAULT_MAX_ATTEMPTS_PER_NEGATIVE = 250
DEFAULT_NEARBY_RADIUS_KM = 10.0
GRID_SIZE_DEGREES = 0.1

OUTPUT_FIELDS = (
    "negative_id",
    "reference_positive_candidate_id",
    "sample_timestamp",
    "latitude",
    "longitude",
    "settlement",
    "settlement_lamas_code",
    "sample_month",
    "sample_hour",
    "nearest_firms_candidate_distance_km",
    "nearest_firms_candidate_time_gap_hours",
    "official_month_support",
    "sample_generation_method",
    "fire_label",
)


class NegativeSampleError(RuntimeError):
    """Generated-input or sampling configuration failure."""


@dataclass(frozen=True)
class FirmsIncident:
    candidate_id: str
    start: datetime
    end: datetime
    latitude: float
    longitude: float


def parse_timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise NegativeSampleError("input timestamp is malformed") from None
    if parsed.tzinfo is None:
        raise NegativeSampleError("input timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def haversine_km(first_lat: float, first_lon: float, second_lat: float, second_lon: float) -> float:
    radius = 6371.0088
    lat1, lat2 = math.radians(first_lat), math.radians(second_lat)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second_lon - first_lon)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(value)))


def incident_time_gap_hours(timestamp: datetime, incident: FirmsIncident) -> float:
    if timestamp < incident.start:
        return (incident.start - timestamp).total_seconds() / 3600
    if timestamp > incident.end:
        return (timestamp - incident.end).total_seconds() / 3600
    return 0.0


def load_positive_references(path: Path = POSITIVE_INPUT) -> list[dict[str, str]]:
    rows = load_csv(path)
    required = {
        "candidate_id", "start_timestamp", "centroid_latitude", "centroid_longitude",
        "settlement", "settlement_lamas_code", "ground_truth_status",
    }
    if not rows or not required.issubset(rows[0]):
        raise NegativeSampleError("positive weather input has an incompatible schema")
    positives = [row for row in rows if row.get("ground_truth_status") == "supported"]
    return sorted(positives, key=lambda row: (row["start_timestamp"], row["candidate_id"]))


def load_firms_incidents(path: Path = FIRMS_INPUT) -> list[FirmsIncident]:
    rows = load_csv(path)
    incidents = []
    try:
        for row in rows:
            start = parse_timestamp(row["start_timestamp"])
            end = parse_timestamp(row["end_timestamp"])
            if end < start:
                raise ValueError
            incidents.append(
                FirmsIncident(
                    candidate_id=row["candidate_id"],
                    start=start,
                    end=end,
                    latitude=float(row["centroid_latitude"]),
                    longitude=float(row["centroid_longitude"]),
                )
            )
    except (KeyError, TypeError, ValueError):
        raise NegativeSampleError("FIRMS candidate input is malformed") from None
    if not incidents:
        raise NegativeSampleError("FIRMS candidate input is empty")
    return sorted(incidents, key=lambda item: (item.start, item.candidate_id))


class FirmsSpaceTimeIndex:
    """Grid index for exclusion queries and exact nearest-point metadata."""

    def __init__(self, incidents: Iterable[FirmsIncident], cell_size: float = GRID_SIZE_DEGREES):
        self.incidents = list(incidents)
        self.cell_size = cell_size
        self.cells: dict[tuple[int, int], list[int]] = {}
        for index, incident in enumerate(self.incidents):
            cell = self._cell(incident.latitude, incident.longitude)
            self.cells.setdefault(cell, []).append(index)
        self.min_x = min(cell[0] for cell in self.cells)
        self.max_x = max(cell[0] for cell in self.cells)
        self.min_y = min(cell[1] for cell in self.cells)
        self.max_y = max(cell[1] for cell in self.cells)

    def _cell(self, latitude: float, longitude: float) -> tuple[int, int]:
        return math.floor(longitude / self.cell_size), math.floor(latitude / self.cell_size)

    def _nearby_indices(self, latitude: float, longitude: float, radius_km: float) -> Iterable[int]:
        x, y = self._cell(latitude, longitude)
        cell_radius = math.ceil(radius_km / (self.cell_size * 90.0)) + 1
        for cell_x in range(x - cell_radius, x + cell_radius + 1):
            for cell_y in range(y - cell_radius, y + cell_radius + 1):
                yield from self.cells.get((cell_x, cell_y), ())

    def is_excluded(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        spatial_radius_km: float,
        temporal_hours: float,
    ) -> bool:
        margin = timedelta(hours=temporal_hours)
        for index in self._nearby_indices(latitude, longitude, spatial_radius_km):
            incident = self.incidents[index]
            if incident.start - margin <= timestamp <= incident.end + margin and haversine_km(
                latitude, longitude, incident.latitude, incident.longitude
            ) <= spatial_radius_km:
                return True
        return False

    def nearest(self, latitude: float, longitude: float, timestamp: datetime) -> tuple[float, float]:
        """Return distance and interval gap for the spatially nearest incident."""
        x, y = self._cell(latitude, longitude)
        best: tuple[float, float, str] | None = None
        maximum_ring = max(
            abs(x - self.min_x), abs(x - self.max_x), abs(y - self.min_y), abs(y - self.max_y)
        )
        for ring in range(maximum_ring + 1):
            cells = []
            if ring == 0:
                cells.append((x, y))
            else:
                for cell_x in range(x - ring, x + ring + 1):
                    cells.extend(((cell_x, y - ring), (cell_x, y + ring)))
                for cell_y in range(y - ring + 1, y + ring):
                    cells.extend(((x - ring, cell_y), (x + ring, cell_y)))
            for cell in cells:
                for index in self.cells.get(cell, ()):
                    incident = self.incidents[index]
                    candidate = (
                        haversine_km(latitude, longitude, incident.latitude, incident.longitude),
                        incident_time_gap_hours(timestamp, incident),
                        incident.candidate_id,
                    )
                    if best is None or candidate < best:
                        best = candidate
            # One degree longitude is at least about 90 km over Israel. This
            # conservative bound may scan an extra ring but cannot skip a
            # spatially closer incident.
            unexplored_lower_bound = max(0, ring - 1) * self.cell_size * 90.0
            if best is not None and best[0] <= unexplored_lower_bound:
                break
        if best is None:
            raise NegativeSampleError("FIRMS spatial index contains no incidents")
        return best[0], best[1]


def _nearby_point(latitude: float, longitude: float, rng: random.Random, maximum_km: float) -> tuple[float, float]:
    distance = rng.uniform(0.5, maximum_km)
    bearing = rng.uniform(0, 2 * math.pi)
    delta_latitude = distance * math.cos(bearing) / 111.32
    longitude_scale = max(0.1, 111.32 * math.cos(math.radians(latitude)))
    delta_longitude = distance * math.sin(bearing) / longitude_scale
    return latitude + delta_latitude, longitude + delta_longitude


def _sample_timestamp(
    reference: datetime,
    minimum: datetime,
    maximum: datetime,
    rng: random.Random,
    prefer_same_month: bool,
) -> tuple[datetime, str]:
    if prefer_same_month:
        month = reference.month
        method = "same_month"
    else:
        month = ((reference.month - 1 + rng.choice((-2, -1, 1, 2))) % 12) + 1
        method = "same_season"
    year = rng.randint(minimum.year, maximum.year)
    day = rng.randint(1, calendar.monthrange(year, month)[1])
    hour = (reference.hour + rng.choice((-1, 0, 0, 0, 1))) % 24
    sampled = datetime(year, month, day, hour, reference.minute, tzinfo=timezone.utc)
    return sampled, method


def _negative_id(reference_id: str, timestamp: datetime, latitude: float, longitude: float) -> str:
    identity = f"{reference_id}|{timestamp.isoformat()}|{latitude:.6f}|{longitude:.6f}"
    return f"negative_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def generate_negative_samples(
    positives: Iterable[Mapping[str, Any]],
    incidents: Iterable[FirmsIncident],
    *,
    settlement_index: SettlementSpatialIndex | None = None,
    official_index: Mapping[tuple[int, int, str], Mapping[str, Any]] | None = None,
    negatives_per_positive: int = DEFAULT_NEGATIVES_PER_POSITIVE,
    spatial_exclusion_km: float = DEFAULT_SPATIAL_EXCLUSION_KM,
    temporal_exclusion_hours: float = DEFAULT_TEMPORAL_EXCLUSION_HOURS,
    seed: int = DEFAULT_RANDOM_SEED,
    max_attempts_per_negative: int = DEFAULT_MAX_ATTEMPTS_PER_NEGATIVE,
    nearby_radius_km: float = DEFAULT_NEARBY_RADIUS_KM,
) -> list[dict[str, Any]]:
    if min(negatives_per_positive, spatial_exclusion_km, temporal_exclusion_hours, max_attempts_per_negative) <= 0:
        raise ValueError("negative sampling parameters must be positive")
    ordered_positives = sorted(positives, key=lambda row: (str(row["start_timestamp"]), str(row["candidate_id"])))
    ordered_incidents = sorted(incidents, key=lambda item: (item.start, item.candidate_id))
    index = FirmsSpaceTimeIndex(ordered_incidents)
    minimum = min(incident.start for incident in ordered_incidents)
    maximum = max(incident.end for incident in ordered_incidents)
    official = official_index or {}
    rng = random.Random(seed)
    used: set[tuple[int, int, int]] = set()
    output = []

    for positive in ordered_positives:
        reference_time = parse_timestamp(positive["start_timestamp"])
        reference_latitude = float(positive["centroid_latitude"])
        reference_longitude = float(positive["centroid_longitude"])
        for slot in range(negatives_per_positive):
            created = False
            for attempt in range(max_attempts_per_negative):
                timestamp, temporal_method = _sample_timestamp(
                    reference_time,
                    minimum,
                    maximum,
                    rng,
                    prefer_same_month=attempt < int(max_attempts_per_negative * 0.8),
                )
                if timestamp < minimum or timestamp > maximum or timestamp == reference_time:
                    continue
                if slot == 0:
                    latitude, longitude = reference_latitude, reference_longitude
                    geographic_method = "same_centroid"
                else:
                    latitude, longitude = _nearby_point(
                        reference_latitude, reference_longitude, rng, nearby_radius_km
                    )
                    geographic_method = "nearby_point"
                duplicate_key = (
                    round(latitude * 100_000),
                    round(longitude * 100_000),
                    int(timestamp.timestamp() // 60),
                )
                if duplicate_key in used or index.is_excluded(
                    latitude,
                    longitude,
                    timestamp,
                    spatial_exclusion_km,
                    temporal_exclusion_hours,
                ):
                    continue
                settlement = settlement_index.locate(latitude, longitude) if settlement_index else None
                code = settlement.lamas_code if settlement else ""
                support = bool(official.get((timestamp.year, timestamp.month, code))) if code else False
                nearest_distance, nearest_gap = index.nearest(latitude, longitude, timestamp)
                row = {
                    "negative_id": _negative_id(str(positive["candidate_id"]), timestamp, latitude, longitude),
                    "reference_positive_candidate_id": positive["candidate_id"],
                    "sample_timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                    "latitude": round(latitude, 6),
                    "longitude": round(longitude, 6),
                    "settlement": settlement.settlement if settlement else "",
                    "settlement_lamas_code": code,
                    "sample_month": timestamp.month,
                    "sample_hour": timestamp.hour,
                    "nearest_firms_candidate_distance_km": round(nearest_distance, 6),
                    "nearest_firms_candidate_time_gap_hours": round(nearest_gap, 6),
                    "official_month_support": "true" if support else "false",
                    "sample_generation_method": f"{geographic_method}_{temporal_method}",
                    "fire_label": 0,
                }
                output.append(row)
                used.add(duplicate_key)
                created = True
                break
            if not created:
                continue
    return sorted(output, key=lambda row: (row["sample_timestamp"], row["negative_id"]))


def write_output(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_negative_dataset(
    *,
    positives_path: Path = POSITIVE_INPUT,
    firms_path: Path = FIRMS_INPUT,
    boundary_path: Path = BOUNDARY_CACHE,
    official_path: Path = FIRE_RESCUE_RECORDS,
    output_path: Path = OUTPUT_PATH,
    negatives_per_positive: int = DEFAULT_NEGATIVES_PER_POSITIVE,
    spatial_exclusion_km: float = DEFAULT_SPATIAL_EXCLUSION_KM,
    temporal_exclusion_hours: float = DEFAULT_TEMPORAL_EXCLUSION_HOURS,
    seed: int = DEFAULT_RANDOM_SEED,
) -> list[dict[str, Any]]:
    positives = load_positive_references(positives_path)
    incidents = load_firms_incidents(firms_path)
    settlements = SettlementSpatialIndex(settlement_polygons(load_boundary_geojson(boundary_path)))
    official = build_official_index(load_csv(official_path))
    rows = generate_negative_samples(
        positives,
        incidents,
        settlement_index=settlements,
        official_index=official,
        negatives_per_positive=negatives_per_positive,
        spatial_exclusion_km=spatial_exclusion_km,
        temporal_exclusion_hours=temporal_exclusion_hours,
        seed=seed,
    )
    write_output(output_path, rows)
    return rows


def summarize(
    rows: list[Mapping[str, Any]], positive_count: int, negatives_per_positive: int
) -> dict[str, Any]:
    per_positive = Counter(str(row["reference_positive_candidate_id"]) for row in rows)
    distances = sorted(float(row["nearest_firms_candidate_distance_km"]) for row in rows)
    gaps = sorted(float(row["nearest_firms_candidate_time_gap_hours"]) for row in rows)
    return {
        "positives": positive_count,
        "target": positive_count * negatives_per_positive,
        "actual": len(rows),
        "negatives_per_positive": dict(sorted(Counter(per_positive.values()).items())),
        "years": dict(sorted(Counter(str(row["sample_timestamp"])[:4] for row in rows).items())),
        "unlocated": sum(not row.get("settlement_lamas_code") for row in rows),
        "unique_settlements": len({row["settlement_lamas_code"] for row in rows if row.get("settlement_lamas_code")}),
        "distance_km": (min(distances), median(distances), max(distances)) if distances else None,
        "time_gap_hours": (min(gaps), median(gaps), max(gaps)) if gaps else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positives", type=Path, default=POSITIVE_INPUT)
    parser.add_argument("--firms-candidates", type=Path, default=FIRMS_INPUT)
    parser.add_argument("--boundaries", type=Path, default=BOUNDARY_CACHE)
    parser.add_argument("--official-records", type=Path, default=FIRE_RESCUE_RECORDS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--negatives-per-positive", type=int, default=DEFAULT_NEGATIVES_PER_POSITIVE)
    parser.add_argument("--spatial-exclusion-km", type=float, default=DEFAULT_SPATIAL_EXCLUSION_KM)
    parser.add_argument("--temporal-exclusion-hours", type=float, default=DEFAULT_TEMPORAL_EXCLUSION_HOURS)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    args = parser.parse_args()
    try:
        positives = load_positive_references(args.positives)
        rows = build_negative_dataset(
            positives_path=args.positives,
            firms_path=args.firms_candidates,
            boundary_path=args.boundaries,
            official_path=args.official_records,
            output_path=args.output,
            negatives_per_positive=args.negatives_per_positive,
            spatial_exclusion_km=args.spatial_exclusion_km,
            temporal_exclusion_hours=args.temporal_exclusion_hours,
            seed=args.seed,
        )
    except (NegativeSampleError, ValueError) as error:
        print(f"Negative-sample build failed: {error}")
        return 1
    print(summarize(rows, len(positives), args.negatives_per_positive))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
