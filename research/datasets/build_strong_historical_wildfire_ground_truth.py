"""Build tiered wildfire ground truth without fabricating event precision."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import rasterio

from research.datasets.build_historical_landcover_terrain_features import (
    LAND_COVER_CLASSES, SOURCE_DIRECTORY, sample_land_cover, worldcover_tile,
)


CURRENT_MATCHED_INPUT = Path("data/generated/firms_fire_rescue_matched_events_2023_2026.csv")
FIRMS_INPUT = Path("data/generated/firms_israel_candidate_incidents_2023_2026.csv")
LANDCOVER_INPUT = Path("data/generated/fire_prediction_ml_landcover_terrain_dataset_2023_2026.csv")
EXTERNAL_EVENTS_INPUT = Path("data/generated/historical_wildfire_external_events_2023_2026.csv")
OUTPUT_PATH = Path("data/generated/historical_wildfire_ground_truth_strong_2023_2026.csv")
SOURCE_SUMMARY_PATH = Path("data/generated/historical_wildfire_ground_truth_sources.json")
START_YEAR, END_YEAR = 2023, 2026
DEFAULT_SPATIAL_TOLERANCE_KM = 5.0
DEFAULT_TEMPORAL_TOLERANCE_HOURS = 72.0

AUTHORITY_LEVELS = {"national_official", "official_emergency_service", "official_land_manager", "government"}
TIMESTAMP_PRECISIONS = {"minute", "hour", "date"}
LOCATION_PRECISIONS = {"coordinates", "point", "area_name", "locality"}
OPEN_LAND_CLASSES = {"tree_cover", "shrubland", "grassland", "cropland", "bare_sparse_vegetation", "herbaceous_wetland"}
OUTPUT_FIELDS = (
    "ground_truth_event_id", "event_timestamp_start", "event_timestamp_end", "latitude", "longitude",
    "location_name", "event_type", "source_name", "source_url_or_identifier", "raw_source_title", "source_authority_level",
    "timestamp_precision", "location_precision", "open_area_indicator", "land_cover_context",
    "firms_support", "firms_candidate_id", "firms_match_status", "firms_match_count",
    "firms_spatial_distance_km", "firms_temporal_gap_hours", "official_support_type",
    "official_event_count", "official_scenarios", "firms_candidates_same_settlement_month",
    "settlement", "settlement_lamas_code", "settlement_match_status", "prior_ground_truth_status",
    "label_confidence_tier", "label_confidence_score", "notes",
)

SOURCE_EVALUATIONS = (
    {
        "source_name": "israel_fire_and_rescue_data_gov_il",
        "authority": "National Fire and Rescue Authority",
        "years_reviewed": "2023-2026",
        "temporal_precision": "month",
        "geographic_precision": "settlement/district aggregate",
        "historical_access": True,
        "machine_readable": True,
        "expected_volume": "35,350 normalized open-area aggregate rows currently cached",
        "access_limitations": "Official resources contain aggregated counts, not event timestamps or coordinates.",
        "independent_of_firms": True,
        "recommended_use": "Tier C monthly supporting evidence only",
        "url": "https://data.gov.il/he/datasets/firefightingcommission/eventsdistrict",
    },
    {
        "source_name": "israel_nature_and_parks_authority_publications",
        "authority": "Israel Nature and Parks Authority",
        "years_reviewed": "2023-2026 public archive",
        "temporal_precision": "publication date; some reports describe event date/hour",
        "geographic_precision": "named reserve/area; occasional multiple named fire locations",
        "historical_access": True,
        "machine_readable": False,
        "expected_volume": "low-volume selected incident and annual-summary publications",
        "access_limitations": "No documented event-level bulk API was found; article extraction and named-area geolocation require review.",
        "independent_of_firms": True,
        "recommended_use": "Curated Tier A/B evidence after human provenance and precision review",
        "url": "https://www.parks.org.il/new/fires-4/",
    },
    {
        "source_name": "kkl_jnf_forest_reports",
        "authority": "KKL-JNF forestry authority/land manager",
        "years_reviewed": "2024-2025 reports located",
        "temporal_precision": "annual/report narrative; some named events include month/date",
        "geographic_precision": "forest or region name; coordinates generally absent",
        "historical_access": True,
        "machine_readable": False,
        "expected_volume": "annual reports and selected publications, not an event feed",
        "access_limitations": "PDF/narrative review required; no documented event-level API was found.",
        "independent_of_firms": True,
        "recommended_use": "Curated supporting evidence, usually Tier B unless precise event details are available",
        "url": "https://www.kkl.org.il/afforestation/forest-data-and-report/",
    },
    {
        "source_name": "official_emergency_public_feeds",
        "authority": "Fire and Rescue / Police / MDA public communications",
        "years_reviewed": "availability varies by channel",
        "temporal_precision": "message timestamp",
        "geographic_precision": "free-text location; variable",
        "historical_access": "not guaranteed",
        "machine_readable": "channel-dependent",
        "expected_volume": "unknown without approved archive acquisition",
        "access_limitations": "Telegram history/session access and channel retention vary; a message alone is supporting evidence, not ground truth.",
        "independent_of_firms": True,
        "recommended_use": "Tier B supporting evidence only when source identity and geocoding precision are preserved",
        "url": None,
    },
)


class StrongGroundTruthError(RuntimeError): pass


def _read_csv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.exists():
        if required: raise StrongGroundTruthError(f"required generated input is missing: {path}")
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle: return list(csv.DictReader(handle))


def _parse_timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _event_interval(value: str, precision: str) -> tuple[datetime, datetime]:
    if precision == "date":
        parsed_date = date.fromisoformat(value)
        start = datetime.combine(parsed_date, time.min, timezone.utc)
        return start, start + timedelta(days=1)
    parsed = _parse_timestamp(value)
    width = timedelta(hours=1) if precision == "hour" else timedelta(minutes=1)
    return parsed, parsed + width


def haversine_km(first_latitude: float, first_longitude: float, second_latitude: float, second_longitude: float) -> float:
    radius = 6371.0088
    lat1, lat2 = math.radians(first_latitude), math.radians(second_latitude)
    delta_lat, delta_lon = lat2 - lat1, math.radians(second_longitude - first_longitude)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def _interval_gap_hours(first_start: datetime, first_end: datetime, second_start: datetime, second_end: datetime) -> float:
    if first_start <= second_end and second_start <= first_end: return 0.0
    return min(abs((first_start - second_end).total_seconds()), abs((second_start - first_end).total_seconds())) / 3600


def load_firms(path: Path = FIRMS_INPUT) -> list[dict[str, Any]]:
    output = []
    for row in _read_csv(path):
        try:
            start, end = _parse_timestamp(row["start_timestamp"]), _parse_timestamp(row["end_timestamp"])
            output.append({**row, "_start": start, "_end": end, "_latitude": float(row["centroid_latitude"]), "_longitude": float(row["centroid_longitude"])})
        except (KeyError, TypeError, ValueError): raise StrongGroundTruthError("FIRMS candidate input is malformed") from None
    return sorted(output, key=lambda row: (row["_start"], row["candidate_id"]))


def match_firms(event: Mapping[str, Any], firms: Iterable[Mapping[str, Any]], *, spatial_tolerance_km: float = DEFAULT_SPATIAL_TOLERANCE_KM, temporal_tolerance_hours: float = DEFAULT_TEMPORAL_TOLERANCE_HOURS) -> dict[str, Any]:
    if event.get("latitude") in {None, ""} or event.get("longitude") in {None, ""}:
        return {"status": "not_attempted_missing_coordinates", "matches": [], "selected": None}
    event_start, event_end = _event_interval(str(event["event_timestamp_start"]), str(event["timestamp_precision"]))
    matches = []
    for candidate in firms:
        gap = _interval_gap_hours(event_start, event_end, candidate["_start"], candidate["_end"])
        if gap > temporal_tolerance_hours: continue
        distance = haversine_km(float(event["latitude"]), float(event["longitude"]), candidate["_latitude"], candidate["_longitude"])
        if distance <= spatial_tolerance_km: matches.append((distance, gap, candidate))
    matches.sort(key=lambda item: (item[0], item[1], item[2]["candidate_id"]))
    return {"status": "matched" if len(matches) == 1 else ("ambiguous_multiple" if matches else "unmatched"), "matches": matches, "selected": matches[0] if matches else None}


def confidence_tier(event: Mapping[str, Any], firms_match: Mapping[str, Any]) -> tuple[str | None, float]:
    if str(event.get("open_area_indicator", "")).lower() != "true": return None, 0.0
    if event.get("source_authority_level") not in AUTHORITY_LEVELS: return None, 0.0
    if event.get("timestamp_precision") not in TIMESTAMP_PRECISIONS or event.get("location_precision") not in LOCATION_PRECISIONS: return None, 0.0
    has_coordinates = event.get("latitude") not in {None, ""} and event.get("longitude") not in {None, ""}
    if has_coordinates and event["timestamp_precision"] in {"minute", "hour"} and event["location_precision"] in {"coordinates", "point"}:
        return "strong_event_support", 0.95
    if has_coordinates and firms_match.get("selected") and event["timestamp_precision"] in {"minute", "hour", "date"}:
        return "multi_source_probable_fire", 0.80
    return None, 0.0


def normalize_external_events(rows: Iterable[Mapping[str, Any]], firms: list[Mapping[str, Any]], land_cover_by_coordinate: Mapping[str, str], *, spatial_tolerance_km: float = DEFAULT_SPATIAL_TOLERANCE_KM, temporal_tolerance_hours: float = DEFAULT_TEMPORAL_TOLERANCE_HOURS) -> tuple[list[dict[str, Any]], dict[str, int]]:
    output, seen = [], set(); rejected = Counter()
    ordered = sorted(rows, key=lambda row: (str(row.get("source_name", "")), str(row.get("source_url_or_identifier", "")), str(row.get("event_timestamp_start", ""))))
    for source in ordered:
        identity = (str(source.get("source_name", "")).strip(), str(source.get("source_url_or_identifier", "")).strip())
        if not all(identity) or identity in seen: rejected["duplicate_or_missing_source_identity"] += 1; continue
        seen.add(identity)
        try:
            precision = str(source["timestamp_precision"]).strip(); timestamp = str(source["event_timestamp_start"]).strip()
            start, _ = _event_interval(timestamp, precision)
            if not START_YEAR <= start.year <= END_YEAR: rejected["outside_year_range"] += 1; continue
            if source.get("latitude") not in {None, ""}: float(source["latitude"]); float(source["longitude"])
        except (KeyError, TypeError, ValueError): rejected["invalid_precision_or_timestamp"] += 1; continue
        match = match_firms(source, firms, spatial_tolerance_km=spatial_tolerance_km, temporal_tolerance_hours=temporal_tolerance_hours)
        tier, score = confidence_tier(source, match)
        if not tier: rejected["insufficient_event_level_support"] += 1; continue
        selected = match["selected"]; candidate = selected[2] if selected else None
        coordinate_key = f"{float(source['latitude']):.6f},{float(source['longitude']):.6f}" if source.get("latitude") not in {None, ""} else ""
        event_id = "wildfire_gt_" + hashlib.sha256("|".join(identity).encode("utf-8")).hexdigest()[:24]
        output.append({
            "ground_truth_event_id": event_id, "event_timestamp_start": timestamp, "event_timestamp_end": str(source.get("event_timestamp_end") or ""),
            "latitude": source.get("latitude", ""), "longitude": source.get("longitude", ""), "location_name": source.get("location_name", ""), "event_type": source.get("event_type", "wildfire"),
            "source_name": identity[0], "source_url_or_identifier": identity[1], "raw_source_title": source.get("raw_source_title", ""), "source_authority_level": source.get("source_authority_level", ""), "timestamp_precision": precision,
            "location_precision": source.get("location_precision", ""), "open_area_indicator": "true", "land_cover_context": land_cover_by_coordinate.get(coordinate_key, ""),
            "firms_support": "true" if candidate else "false", "firms_candidate_id": candidate["candidate_id"] if candidate else "", "firms_match_status": match["status"], "firms_match_count": len(match["matches"]),
            "firms_spatial_distance_km": round(selected[0], 6) if selected else "", "firms_temporal_gap_hours": round(selected[1], 6) if selected else "", "official_support_type": "independent_event_level_source",
            "official_event_count": "", "official_scenarios": "", "firms_candidates_same_settlement_month": "", "settlement": "", "settlement_lamas_code": "", "settlement_match_status": "not_evaluated_for_external_event", "prior_ground_truth_status": "",
            "label_confidence_tier": tier, "label_confidence_score": score, "notes": str(source.get("notes") or ""),
        })
    return output, dict(rejected)


def current_tier_c_rows(matched_rows: Iterable[Mapping[str, Any]], land_cover_by_candidate: Mapping[str, str]) -> list[dict[str, Any]]:
    output = []
    for row in matched_rows:
        if row.get("ground_truth_status") != "supported": continue
        candidate_id = str(row["candidate_id"]); scenarios = str(row.get("official_scenarios") or "")
        output.append({
            "ground_truth_event_id": f"wildfire_gt_monthly_{candidate_id}", "event_timestamp_start": row["start_timestamp"], "event_timestamp_end": row.get("end_timestamp", ""),
            "latitude": row["centroid_latitude"], "longitude": row["centroid_longitude"], "location_name": row.get("settlement", ""), "event_type": scenarios or "official_open_area_wildfire_scenario",
            "source_name": "nasa_firms;israel_fire_and_rescue", "source_url_or_identifier": candidate_id, "raw_source_title": "", "source_authority_level": "government", "timestamp_precision": "minute",
            "location_precision": "coordinates", "open_area_indicator": "true", "land_cover_context": land_cover_by_candidate.get(candidate_id, ""), "firms_support": "true", "firms_candidate_id": candidate_id,
            "firms_match_status": "source_candidate", "firms_match_count": 1, "firms_spatial_distance_km": 0.0, "firms_temporal_gap_hours": 0.0,
            "official_support_type": "same_settlement_month_aggregate", "label_confidence_tier": "weak_monthly_support", "label_confidence_score": 0.60,
            "official_event_count": row.get("official_event_count", ""), "official_scenarios": scenarios, "firms_candidates_same_settlement_month": row.get("firms_candidates_same_settlement_month", ""),
            "settlement": row.get("settlement", ""), "settlement_lamas_code": row.get("settlement_lamas_code", ""), "settlement_match_status": row.get("settlement_match_status", ""), "prior_ground_truth_status": row.get("ground_truth_status", ""),
            "notes": "Official support is monthly aggregated and does not identify this individual FIRMS candidate.",
        })
    return output


def build(*, matched_path: Path = CURRENT_MATCHED_INPUT, firms_path: Path = FIRMS_INPUT, landcover_path: Path = LANDCOVER_INPUT, external_path: Path = EXTERNAL_EVENTS_INPUT, output_path: Path = OUTPUT_PATH, source_summary_path: Path = SOURCE_SUMMARY_PATH, spatial_tolerance_km: float = DEFAULT_SPATIAL_TOLERANCE_KM, temporal_tolerance_hours: float = DEFAULT_TEMPORAL_TOLERANCE_HOURS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    matched, firms, land_rows = _read_csv(matched_path), load_firms(firms_path), _read_csv(landcover_path)
    land_by_candidate = {row["sample_id"]: row.get("land_cover_source_class", "") for row in land_rows if row.get("sample_id")}
    land_by_coordinate = {f"{float(row['latitude']):.6f},{float(row['longitude']):.6f}": row.get("land_cover_source_class", "") for row in land_rows if row.get("latitude") and row.get("longitude")}
    external_source_rows = _read_csv(external_path, required=False)
    datasets = {}
    try:
        for row in external_source_rows:
            if row.get("latitude") in {None, ""} or row.get("longitude") in {None, ""}: continue
            latitude, longitude = float(row["latitude"]), float(row["longitude"])
            key = f"{latitude:.6f},{longitude:.6f}"
            if key in land_by_coordinate: continue
            filename, _ = worldcover_tile(latitude, longitude); path = SOURCE_DIRECTORY / "worldcover_2021" / filename
            if not path.exists(): continue
            if filename not in datasets: datasets[filename] = rasterio.open(path)
            code = sample_land_cover(datasets[filename], latitude, longitude)
            land_by_coordinate[key] = LAND_COVER_CLASSES.get(code, "")
    finally:
        for dataset in datasets.values(): dataset.close()
    external, rejected = normalize_external_events(external_source_rows, firms, land_by_coordinate, spatial_tolerance_km=spatial_tolerance_km, temporal_tolerance_hours=temporal_tolerance_hours)
    tier_c = current_tier_c_rows(matched, land_by_candidate)
    current_by_candidate = {str(row.get("candidate_id")): row for row in matched}
    for row in external:
        current = current_by_candidate.get(str(row.get("firms_candidate_id")))
        if not current: continue
        row.update({"official_event_count": current.get("official_event_count", ""), "official_scenarios": current.get("official_scenarios", ""), "firms_candidates_same_settlement_month": current.get("firms_candidates_same_settlement_month", ""), "settlement": current.get("settlement", ""), "settlement_lamas_code": current.get("settlement_lamas_code", ""), "settlement_match_status": current.get("settlement_match_status", ""), "prior_ground_truth_status": current.get("ground_truth_status", "")})
        if current.get("official_month_support") == "true": row["official_support_type"] += ";same_settlement_month_aggregate"
    upgraded_candidates = {row["firms_candidate_id"] for row in external if row["firms_candidate_id"]}
    rows = external + [row for row in tier_c if row["firms_candidate_id"] not in upgraded_candidates]
    rows.sort(key=lambda row: (str(row["event_timestamp_start"]), str(row["ground_truth_event_id"])))
    output_path.parent.mkdir(parents=True, exist_ok=True); temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    temporary.replace(output_path)
    tiers, years, land = Counter(row["label_confidence_tier"] for row in rows), Counter(str(row["event_timestamp_start"])[:4] for row in rows), Counter(row["land_cover_context"] or "unavailable" for row in rows)
    summary = {"schema_version": 1, "parameters": {"years": [START_YEAR, END_YEAR], "spatial_tolerance_km": spatial_tolerance_km, "temporal_tolerance_hours": temporal_tolerance_hours}, "source_evaluations": SOURCE_EVALUATIONS, "external_input_present": external_path.exists(), "external_rows_accepted": len(external), "external_rows_rejected": rejected, "statistics": {"total": len(rows), "by_tier": dict(tiers), "by_year": dict(years), "by_land_cover": dict(land), "by_timestamp_precision": dict(Counter(row["timestamp_precision"] for row in rows)), "by_location_precision": dict(Counter(row["location_precision"] for row in rows)), "mapped_to_settlement": sum(bool(row["settlement_lamas_code"]) for row in rows), "not_settlement_mapped": sum(not bool(row["settlement_lamas_code"]) for row in rows), "firms_matched": sum(row["firms_support"] == "true" for row in rows), "firms_unmatched": sum(row["firms_support"] != "true" for row in rows), "ambiguous_firms_matches": sum(row["firms_match_status"] == "ambiguous_multiple" for row in rows), "duplicate_event_ids": len(rows) - len({row["ground_truth_event_id"] for row in rows}), "individually_supported_open_area": sum(row["label_confidence_tier"] in {"strong_event_support", "multi_source_probable_fire"} and row["open_area_indicator"] == "true" for row in rows)}}
    source_summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"); return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--external-events", type=Path, default=EXTERNAL_EVENTS_INPUT); parser.add_argument("--spatial-tolerance-km", type=float, default=DEFAULT_SPATIAL_TOLERANCE_KM); parser.add_argument("--temporal-tolerance-hours", type=float, default=DEFAULT_TEMPORAL_TOLERANCE_HOURS); args = parser.parse_args()
    try: rows, summary = build(external_path=args.external_events, spatial_tolerance_km=args.spatial_tolerance_km, temporal_tolerance_hours=args.temporal_tolerance_hours)
    except (StrongGroundTruthError, OSError, csv.Error) as error: print(f"Strong ground-truth build failed: {error}"); return 1
    print(json.dumps(summary["statistics"], ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
