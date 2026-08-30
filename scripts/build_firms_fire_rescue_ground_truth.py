"""Map historical FIRMS candidates to official settlement/month aggregates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BOUNDARY_SERVICE = (
    "https://services-eu1.arcgis.com/ORARfqfyRwgjcEva/ArcGIS/rest/services/"
    "%D7%92%D7%91%D7%95%D7%9C%D7%95%D7%AA_%D7%A9%D7%99%D7%A4%D7%95%D7%98_"
    "%D7%A8%D7%A9%D7%95%D7%99%D7%95%D7%AA_%D7%9E%D7%A7%D7%95%D7%9E%D7%99%D7%95%D7%AA/"
    "FeatureServer/1/query"
)
BOUNDARY_SOURCE = (
    "Knesset Research and Information Center muni_vaadim FeatureServer "
    "(Ministry of Interior statutory-boundary layer)"
)
USER_AGENT = "EcoGuard-Agents settlement-boundary-builder/1.0"
REQUEST_TIMEOUT_SECONDS = 90
PAGE_SIZE = 1000
GRID_SIZE_DEGREES = 0.1

BOUNDARY_CACHE = Path("data/generated/israel_settlement_boundaries.geojson")
BOUNDARY_MANIFEST = Path(
    "data/generated/israel_settlement_boundaries.manifest.json"
)
FIRMS_CANDIDATES = Path(
    "data/generated/firms_israel_candidate_incidents_2023_2026.csv"
)
FIRE_RESCUE_RECORDS = Path(
    "data/generated/israel_fire_rescue_open_area_2023_2026.csv"
)
OUTPUT_PATH = Path(
    "data/generated/firms_fire_rescue_matched_events_2023_2026.csv"
)

RELEVANT_SCENARIOS = frozenset(
    {
        "שריפת צמחייה באינדקס רגיל",
        "שריפת צמחייה באינדקס גבוה / קיצון",
        "שריפת יער",
    }
)

OUTPUT_FIELDS = (
    "candidate_id",
    "start_timestamp",
    "end_timestamp",
    "centroid_latitude",
    "centroid_longitude",
    "hotspot_count",
    "max_frp",
    "mean_frp",
    "satellites",
    "source_products",
    "duration_hours",
    "settlement",
    "settlement_lamas_code",
    "settlement_match_status",
    "official_month_support",
    "firms_candidates_same_settlement_month",
    "official_event_count",
    "official_scenarios",
    "ground_truth_status",
)


class GroundTruthBuildError(RuntimeError):
    """Safe source, cache, geometry, or input error."""


@dataclass(frozen=True)
class SettlementPolygon:
    settlement: str
    lamas_code: str
    geometry: dict[str, Any]
    bounds: tuple[float, float, float, float]
    specific_locality: bool
    area_hint: float


def normalize_lamas_code(value: object) -> str:
    text = str(value or "").strip()
    if not text or text in {"-", "0"}:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if not number.is_integer() or number < 0:
        return ""
    return str(int(number)).zfill(4)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json, application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise GroundTruthBuildError(
            f"official boundary provider returned HTTP {error.code}"
        ) from None
    except urllib.error.URLError as error:
        reason = "timeout" if isinstance(error.reason, TimeoutError) else "network error"
        raise GroundTruthBuildError(f"official boundary provider {reason}") from None
    except (TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
        raise GroundTruthBuildError(
            "official boundary provider returned a malformed response"
        ) from None
    if not isinstance(result, dict):
        raise GroundTruthBuildError(
            "official boundary provider returned a malformed response"
        )
    return result


def download_boundary_cache(
    cache_path: Path = BOUNDARY_CACHE,
    manifest_path: Path = BOUNDARY_MANIFEST,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        parameters = {
            "where": "1=1",
            "outFields": "FID,Muni_Heb,CR_LAMAS,Vaad_Heb,CV_LAMAS,Shape_Area,AreaSQM",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "orderByFields": "FID ASC",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
        }
        page = _fetch_json(
            f"{BOUNDARY_SERVICE}?{urllib.parse.urlencode(parameters)}"
        )
        page_features = page.get("features")
        if page.get("type") != "FeatureCollection" or not isinstance(page_features, list):
            raise GroundTruthBuildError(
                "official boundary provider returned invalid GeoJSON"
            )
        features.extend(page_features)
        if len(page_features) < PAGE_SIZE:
            break
        offset += len(page_features)
        time.sleep(0.2)

    collection = {"type": "FeatureCollection", "features": features}
    validate_boundary_geojson(collection)
    usable_features = sum(
        bool(normalize_lamas_code((feature.get("properties") or {}).get("CV_LAMAS")))
        or bool(normalize_lamas_code((feature.get("properties") or {}).get("CR_LAMAS")))
        for feature in features
    )
    content = json.dumps(
        collection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    manifest = {
        "source": BOUNDARY_SOURCE,
        "service": BOUNDARY_SERVICE,
        "downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feature_count": len(features),
        "usable_feature_count": usable_features,
        "features_without_lamas_code": len(features) - usable_features,
        "sha256": digest,
    }
    _atomic_text(cache_path, content)
    _atomic_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
    )
    return manifest


def validate_boundary_geojson(collection: Mapping[str, Any]) -> None:
    features = collection.get("features")
    if collection.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise GroundTruthBuildError("boundary cache is invalid GeoJSON")
    if not features:
        raise GroundTruthBuildError("boundary cache contains no polygons")
    usable_features = 0
    for feature in features:
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise GroundTruthBuildError("boundary cache contains non-polygon geometry")
        locality_code = normalize_lamas_code(properties.get("CV_LAMAS"))
        municipality_code = normalize_lamas_code(properties.get("CR_LAMAS"))
        if locality_code or municipality_code:
            usable_features += 1
    if not usable_features:
        raise GroundTruthBuildError("boundary cache has no polygons with LAMAS codes")


def load_boundary_geojson(path: Path = BOUNDARY_CACHE) -> dict[str, Any]:
    if not path.exists():
        raise GroundTruthBuildError(
            "official settlement-boundary cache is missing; run with --refresh-boundaries"
        )
    try:
        collection = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise GroundTruthBuildError("boundary cache is corrupted") from None
    validate_boundary_geojson(collection)
    return collection


def _iter_points(value: Any) -> Iterable[tuple[float, float]]:
    if (
        isinstance(value, Sequence)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _iter_points(item)


def _geometry_bounds(geometry: Mapping[str, Any]) -> tuple[float, float, float, float]:
    points = list(_iter_points(geometry.get("coordinates")))
    if not points:
        raise GroundTruthBuildError("boundary polygon has no coordinates")
    longitudes, latitudes = zip(*points)
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def settlement_polygons(collection: Mapping[str, Any]) -> list[SettlementPolygon]:
    polygons = []
    for feature in collection["features"]:
        properties = feature.get("properties") or {}
        locality_code = normalize_lamas_code(properties.get("CV_LAMAS"))
        specific = bool(locality_code)
        code = locality_code or normalize_lamas_code(properties.get("CR_LAMAS"))
        name = str(
            (properties.get("Vaad_Heb") if specific else properties.get("Muni_Heb"))
            or ""
        ).strip()
        if not code or not name:
            continue
        geometry = feature["geometry"]
        bounds = _geometry_bounds(geometry)
        area_value = properties.get("AreaSQM") or properties.get("Shape_Area")
        try:
            area_hint = float(area_value)
        except (TypeError, ValueError):
            area_hint = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        polygons.append(
            SettlementPolygon(name, code, geometry, bounds, specific, area_hint)
        )
    if not polygons:
        raise GroundTruthBuildError("boundary cache has no usable settlement polygons")
    return polygons


def _point_on_segment(
    x: float, y: float, first: Sequence[float], second: Sequence[float]
) -> bool:
    x1, y1, x2, y2 = float(first[0]), float(first[1]), float(second[0]), float(second[1])
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > 1e-12:
        return False
    return min(x1, x2) - 1e-12 <= x <= max(x1, x2) + 1e-12 and min(
        y1, y2
    ) - 1e-12 <= y <= max(y1, y2) + 1e-12


def _point_in_ring(longitude: float, latitude: float, ring: Sequence[Sequence[float]]) -> bool:
    inside = False
    for index, first in enumerate(ring):
        second = ring[(index + 1) % len(ring)]
        if _point_on_segment(longitude, latitude, first, second):
            return True
        y1, y2 = float(first[1]), float(second[1])
        if (y1 > latitude) != (y2 > latitude):
            intersection = (float(second[0]) - float(first[0])) * (
                latitude - y1
            ) / (y2 - y1) + float(first[0])
            if longitude < intersection:
                inside = not inside
    return inside


def _point_in_polygon(
    longitude: float, latitude: float, rings: Sequence[Sequence[Sequence[float]]]
) -> bool:
    return bool(rings) and _point_in_ring(longitude, latitude, rings[0]) and not any(
        _point_in_ring(longitude, latitude, hole) for hole in rings[1:]
    )


def point_in_geometry(longitude: float, latitude: float, geometry: Mapping[str, Any]) -> bool:
    if geometry["type"] == "Polygon":
        return _point_in_polygon(longitude, latitude, geometry["coordinates"])
    return any(
        _point_in_polygon(longitude, latitude, polygon)
        for polygon in geometry["coordinates"]
    )


class SettlementSpatialIndex:
    def __init__(self, polygons: list[SettlementPolygon], cell_size: float = GRID_SIZE_DEGREES):
        self.polygons = polygons
        self.cell_size = cell_size
        self.cells: dict[tuple[int, int], list[int]] = defaultdict(list)
        for index, polygon in enumerate(polygons):
            west, south, east, north = polygon.bounds
            for x in range(math.floor(west / cell_size), math.floor(east / cell_size) + 1):
                for y in range(math.floor(south / cell_size), math.floor(north / cell_size) + 1):
                    self.cells[(x, y)].append(index)

    def locate(self, latitude: float, longitude: float) -> SettlementPolygon | None:
        cell = (math.floor(longitude / self.cell_size), math.floor(latitude / self.cell_size))
        matches = []
        for index in self.cells.get(cell, []):
            polygon = self.polygons[index]
            west, south, east, north = polygon.bounds
            if west <= longitude <= east and south <= latitude <= north and point_in_geometry(
                longitude, latitude, polygon.geometry
            ):
                matches.append(polygon)
        if not matches:
            return None
        return min(
            matches,
            key=lambda polygon: (
                not polygon.specific_locality,
                polygon.area_hint,
                polygon.lamas_code,
                polygon.settlement,
            ),
        )


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise GroundTruthBuildError(f"required generated input is missing: {path}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        raise GroundTruthBuildError(f"generated input is malformed: {path}") from None


def build_official_index(
    records: Iterable[Mapping[str, Any]],
) -> dict[tuple[int, int, str], dict[str, Any]]:
    grouped: dict[tuple[int, int, str], dict[str, Any]] = {}
    for row in records:
        scenario = str(row.get("scenario") or "").strip()
        if scenario not in RELEVANT_SCENARIOS:
            continue
        try:
            year = int(str(row.get("year")).strip())
            month = int(str(row.get("month")).strip())
            count = int(str(row.get("event_count")).strip())
        except (TypeError, ValueError):
            continue
        code = normalize_lamas_code(row.get("settlement_lamas_code"))
        if not code or not 1 <= month <= 12 or count < 0:
            continue
        key = (year, month, code)
        entry = grouped.setdefault(key, {"event_count": 0, "scenarios": set()})
        entry["event_count"] += count
        entry["scenarios"].add(scenario)
    return grouped


def _candidate_year_month(timestamp: object) -> tuple[int, int]:
    parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    return parsed.year, parsed.month


def match_candidates(
    candidates: Iterable[Mapping[str, Any]],
    spatial_index: SettlementSpatialIndex,
    official_index: Mapping[tuple[int, int, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    prepared = []
    candidate_counts: dict[tuple[int, int, str], int] = defaultdict(int)
    for candidate in candidates:
        try:
            latitude = float(candidate["centroid_latitude"])
            longitude = float(candidate["centroid_longitude"])
            year, month = _candidate_year_month(candidate["start_timestamp"])
        except (KeyError, TypeError, ValueError):
            raise GroundTruthBuildError("FIRMS candidate input is malformed") from None
        settlement = spatial_index.locate(latitude, longitude)
        key = (year, month, settlement.lamas_code) if settlement else None
        if key:
            candidate_counts[key] += 1
        prepared.append((candidate, settlement, key))

    matched = []
    for candidate, settlement, key in prepared:
        official = (
            official_index.get(key) if key else None
        )
        output = {field: candidate.get(field, "") for field in OUTPUT_FIELDS[:11]}
        output.update(
            {
                "settlement": settlement.settlement if settlement else "",
                "settlement_lamas_code": settlement.lamas_code if settlement else "",
                "settlement_match_status": "inside_official_polygon"
                if settlement
                else "outside_official_settlement_polygon",
                "official_month_support": "true" if official else "false",
                "firms_candidates_same_settlement_month": candidate_counts.get(key, 0),
                # This is the full monthly aggregate and is never allocated or
                # decremented per FIRMS candidate.
                "official_event_count": int(official["event_count"]) if official else 0,
                "official_scenarios": ";".join(sorted(official["scenarios"]))
                if official
                else "",
                "ground_truth_status": "supported"
                if official
                else ("unsupported" if settlement else "unlocated"),
            }
        )
        matched.append(output)
    return sorted(
        matched, key=lambda row: (str(row["start_timestamp"]), str(row["candidate_id"]))
    )


def write_output(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_ground_truth(
    *,
    boundary_cache: Path = BOUNDARY_CACHE,
    candidates_path: Path = FIRMS_CANDIDATES,
    official_path: Path = FIRE_RESCUE_RECORDS,
    output_path: Path = OUTPUT_PATH,
) -> list[dict[str, Any]]:
    polygons = settlement_polygons(load_boundary_geojson(boundary_cache))
    candidates = load_csv(candidates_path)
    official = build_official_index(load_csv(official_path))
    output = match_candidates(candidates, SettlementSpatialIndex(polygons), official)
    write_output(output_path, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-boundaries", action="store_true")
    parser.add_argument("--boundary-cache", type=Path, default=BOUNDARY_CACHE)
    parser.add_argument("--boundary-manifest", type=Path, default=BOUNDARY_MANIFEST)
    parser.add_argument("--candidates", type=Path, default=FIRMS_CANDIDATES)
    parser.add_argument("--official-records", type=Path, default=FIRE_RESCUE_RECORDS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    try:
        if args.refresh_boundaries or not args.boundary_cache.exists():
            manifest = download_boundary_cache(
                args.boundary_cache, args.boundary_manifest
            )
            print(
                f"Cached {manifest['feature_count']} official settlement-boundary features."
            )
        output = build_ground_truth(
            boundary_cache=args.boundary_cache,
            candidates_path=args.candidates,
            official_path=args.official_records,
            output_path=args.output,
        )
    except GroundTruthBuildError as error:
        print(f"Ground-truth build failed: {error}")
        return 1
    print(f"Matched FIRMS candidates: {len(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
