"""Reconstruct and score independent Tier B historical wildfire case studies."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping

import numpy as np
import rasterio
from rasterio.windows import Window

from agents.fire_risk_prediction_agent import FireRiskPredictionAgent
from scripts.build_historical_environmental_features import (
    PriorFirmsIndex,
    historical_fire_features,
)
from scripts.build_historical_fire_negative_samples import FirmsIncident, load_firms_incidents, parse_timestamp
from scripts.build_historical_fire_weather_features import (
    FEATURE_FIELDS,
    OpenMeteoHistoricalClient,
    ProviderError,
    WeatherCheckpoint,
    checkpoint_configuration,
    compute_features,
)
from scripts.build_historical_landcover_terrain_features import (
    LAND_COVER_CLASSES,
    SOURCE_DIRECTORY,
    collect_static_features,
    dem_tile,
    enrich_rows as enrich_static_rows,
)
from scripts.train_fire_prediction_landcover_terrain_models import FULL_FEATURES

STRONG_INPUT = Path("data/generated/historical_wildfire_ground_truth_strong_2023_2026.csv")
TELEGRAM_INPUT = Path("data/generated/historical_wildfire_telegram_pilot_2023_2026.csv")
FIRMS_INPUT = Path("data/generated/firms_israel_candidate_incidents_2023_2026.csv")
FEATURE_OUTPUT = Path("data/generated/fire_risk_strong_event_case_study_features.csv")
RESULT_OUTPUT = Path("data/generated/fire_risk_strong_event_case_study_results.csv")
TRAJECTORY_OUTPUT = Path("data/generated/fire_risk_strong_event_trajectory_results.csv")
REPORT_OUTPUT = Path("docs/fire_risk_strong_event_case_study.md")
WEATHER_CHECKPOINT = Path("data/generated/fire_risk_strong_event_weather_checkpoint")
STATIC_CACHE = Path("data/generated/fire_risk_strong_event_static_cache.json")
TIER_B = "multi_source_probable_fire"


class CaseStudyError(RuntimeError):
    pass


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise CaseStudyError(f"required generated input is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def discover_tier_b_events(strong_path: Path = STRONG_INPUT, telegram_path: Path = TELEGRAM_INPUT) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in _read(strong_path):
        if row.get("label_confidence_tier") != TIER_B:
            continue
        events.append({
            "event_id": row["ground_truth_event_id"], "source": row["source_name"], "source_type": "official_report",
            "source_identifier": row["source_url_or_identifier"], "event_timestamp": row["event_timestamp_start"],
            "timestamp_precision": row["timestamp_precision"], "latitude": row["latitude"], "longitude": row["longitude"],
            "location": row["location_name"], "location_precision": row["location_precision"],
            "coordinate_basis": f"geocoded_{row['location_precision']}_reference_not_exact_event_point",
            "tier": row["label_confidence_tier"], "tier_score": row["label_confidence_score"],
            "firms_candidate_id": row["firms_candidate_id"], "firms_match_status": row["firms_match_status"],
            "firms_match_count": row["firms_match_count"], "firms_distance_km": row["firms_spatial_distance_km"],
            "firms_time_gap_hours": row["firms_temporal_gap_hours"], "notes": row.get("notes", ""),
        })
    for row in _read(telegram_path):
        if row.get("label_confidence_tier") != TIER_B:
            continue
        events.append({
            "event_id": row["telegram_event_id"], "source": row["channel_name"], "source_type": "verified_telegram",
            "source_identifier": row["telegram_source_url_or_identifier"], "event_timestamp": row["message_timestamp"],
            "timestamp_precision": row["timestamp_precision"], "latitude": row["latitude"], "longitude": row["longitude"],
            "location": row["location_text"], "location_precision": row["location_precision"],
            "coordinate_basis": f"geocoded_{row['location_precision']}_reference_not_exact_event_point",
            "tier": row["label_confidence_tier"], "tier_score": "0.80",
            "firms_candidate_id": row["firms_candidate_id"], "firms_match_status": row["firms_match_status"],
            "firms_match_count": row["firms_match_count"], "firms_distance_km": row["firms_distance_km"],
            "firms_time_gap_hours": row["firms_time_gap_hours"], "notes": row.get("notes", ""),
        })
    unique: dict[str, dict[str, Any]] = {}
    for event in sorted(events, key=lambda item: (item["event_timestamp"], item["source_type"], item["event_id"])):
        identity = event["event_id"]
        if identity in unique:
            raise CaseStudyError(f"duplicate Tier B event identifier: {identity}")
        unique[identity] = event
    return list(unique.values())


def resolve_reference_time(event: Mapping[str, Any], firms_by_id: Mapping[str, FirmsIncident]) -> tuple[datetime | None, str, str]:
    precision = event.get("timestamp_precision")
    if precision in {"minute", "hour"}:
        try:
            return parse_timestamp(event["event_timestamp"]), "source_event_timestamp", ""
        except Exception:
            return None, "", "malformed source timestamp"
    if precision == "date":
        candidate = firms_by_id.get(str(event.get("firms_candidate_id", "")))
        if candidate is None:
            return None, "", "date-only event has no retained matched FIRMS candidate timestamp"
        return candidate.start, "matched_firms_acquisition_for_date_only_event", ""
    return None, "", f"unsupported timestamp precision: {precision}"


def _sample_elevation(latitude: float, longitude: float, source_directory: Path = SOURCE_DIRECTORY) -> float | None:
    filename, _ = dem_tile(latitude, longitude)
    path = source_directory / "copernicus_dem_glo90" / filename
    if not path.exists():
        return None
    with rasterio.open(path) as dataset:
        try:
            row, column = dataset.index(longitude, latitude)
            value = float(dataset.read(1, window=Window(column, row, 1, 1))[0, 0])
        except (IndexError, ValueError):
            return None
        return value if math.isfinite(value) else None


def non_weather_features(
    event: Mapping[str, Any], reference_time: datetime, index: PriorFirmsIndex,
    static_value: Mapping[str, Any], elevation: float | None,
) -> dict[str, Any]:
    day = reference_time.timetuple().tm_yday
    values: dict[str, Any] = {
        "sin_day_of_year": math.sin(2 * math.pi * day / 365.25),
        "cos_day_of_year": math.cos(2 * math.pi * day / 365.25),
        "sin_hour": math.sin(2 * math.pi * reference_time.hour / 24),
        "cos_hour": math.cos(2 * math.pi * reference_time.hour / 24),
        "elevation_m": elevation,
    }
    values.update(historical_fire_features(
        index, float(event["latitude"]), float(event["longitude"]), reference_time,
        excluded_candidate_ids=[str(event.get("firms_candidate_id", ""))],
    ))
    code = static_value.get("land_cover_code")
    for class_code, class_name in LAND_COVER_CLASSES.items():
        values[f"land_cover_{class_name}"] = int(code == class_code)
    values["slope_degrees"] = static_value.get("slope_degrees")
    return values


def _weather_candidate(event: Mapping[str, Any], reference_time: datetime) -> dict[str, str]:
    return {
        "candidate_id": str(event["event_id"]), "start_timestamp": reference_time.isoformat(),
        "centroid_latitude": str(event["latitude"]), "centroid_longitude": str(event["longitude"]),
    }


def reconstruct_features(
    events: list[dict[str, Any]], incidents: list[FirmsIncident], *,
    weather_client: OpenMeteoHistoricalClient | None = None,
    weather_checkpoint_path: Path = WEATHER_CHECKPOINT, static_cache_path: Path = STATIC_CACHE,
    source_directory: Path = SOURCE_DIRECTORY, logger=print,
) -> list[dict[str, Any]]:
    firms_by_id = {incident.candidate_id: incident for incident in incidents}
    index = PriorFirmsIndex(incidents)
    static_rows = [{"latitude": event["latitude"], "longitude": event["longitude"]} for event in events]
    static_cache = collect_static_features(static_rows, source_directory=source_directory, cache_path=static_cache_path, logger=logger)
    static_enriched = enrich_static_rows(static_rows, static_cache)
    static_by_coordinate = {
        (str(row["latitude"]), str(row["longitude"])): {
            "land_cover_code": row.get("land_cover_source_code"), "slope_degrees": row.get("slope_degrees"),
        }
        for row in static_enriched
    }
    provider = weather_client or OpenMeteoHistoricalClient()
    checkpoint = WeatherCheckpoint(weather_checkpoint_path, checkpoint_configuration(provider.endpoint))
    checkpoint.initialize()
    output = []
    for number, event in enumerate(events, 1):
        row = dict(event)
        reference_time, basis, reason = resolve_reference_time(event, firms_by_id)
        row.update({"evaluation_reference_time": reference_time.isoformat() if reference_time else "", "reference_time_basis": basis})
        feature_values = {name: None for name in FULL_FEATURES}
        status = "incomplete"
        if reference_time is not None:
            candidate = _weather_candidate(event, reference_time)
            try:
                weather = checkpoint.load(candidate)
                if weather is None:
                    weather = provider.fetch(float(event["latitude"]), float(event["longitude"]), reference_time)
                    checkpoint.save(candidate, weather)
                weather_values, weather_status = compute_features(weather, reference_time)
                feature_values.update(weather_values)
                coordinate = (str(event["latitude"]), str(event["longitude"]))
                feature_values.update(non_weather_features(
                    event, reference_time, index, static_by_coordinate.get(coordinate, {}),
                    _sample_elevation(float(event["latitude"]), float(event["longitude"]), source_directory),
                ))
                missing = [name for name in FULL_FEATURES if feature_values.get(name) is None]
                if missing:
                    reason = f"missing required features: {', '.join(missing)}; weather_status={weather_status}"
                else:
                    status, reason = "complete", ""
            except ProviderError as error:
                reason = f"weather provider {error.category}"
        row.update({"feature_status": status, "missing_feature_reason": reason, **feature_values})
        output.append(row)
        logger(f"Case-study features: {number}/{len(events)} {event['event_id']} status={status}")
    return output


def score_rows(rows: list[Mapping[str, Any]], agent: FireRiskPredictionAgent | None = None) -> list[dict[str, Any]]:
    predictor = agent or FireRiskPredictionAgent()
    output = []
    for row in rows:
        result = {"risk_score": "", "risk_level": "", "model_version": "", "calibration_method": "", "low_medium_threshold": "", "medium_high_threshold": "", "main_factors": ""}
        if row["feature_status"] == "complete":
            prediction = predictor.predict({name: row[name] for name in FULL_FEATURES})
            if prediction["status"] == "ok":
                metadata = predictor.calibration_metadata
                result.update({
                    "risk_score": prediction["risk_score"], "risk_level": prediction["risk_level"],
                    "model_version": prediction["model_version"], "calibration_method": metadata["calibration"]["method"],
                    "low_medium_threshold": metadata["low_medium_threshold"], "medium_high_threshold": metadata["medium_high_threshold"],
                    "main_factors": json.dumps(prediction["main_factors"], ensure_ascii=False, separators=(",", ":")),
                })
            else:
                result["main_factors"] = json.dumps(prediction["error"], ensure_ascii=False)
        output.append({**row, **result})
    return output


def trajectory_events(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for event in events:
        if event.get("timestamp_precision") not in {"minute", "hour"}:
            continue
        reference, _, reason = resolve_reference_time(event, {})
        if reference is None:
            raise CaseStudyError(reason)
        for hours in (12, 6, 3):
            trajectory = dict(event)
            trajectory.update({
                "original_event_id": event["event_id"], "trajectory_offset_hours": -hours,
                "event_id": f"{event['event_id']}__t_minus_{hours}h",
                "event_timestamp": (reference - timedelta(hours=hours)).isoformat(),
            })
            output.append(trajectory)
    return output


def _atomic_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fields = list(rows[0])
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def write_report(path: Path, rows: list[Mapping[str, Any]], trajectories: list[Mapping[str, Any]]) -> None:
    complete = [row for row in rows if row["risk_score"] != ""]
    levels = Counter(row["risk_level"] for row in complete)
    scores = [float(row["risk_score"]) for row in complete]
    lines = [
        "# Fire Risk Strong-Event Case Study", "",
        "These Tier B cases are independent qualitative event checks. They were not used to fit the model, calibration, thresholds, or model selection. Results indicate face validity or qualitative consistency only—not accuracy, recall, sensitivity, or statistical validation.", "",
        "## Coverage", "",
        f"- Tier B events discovered: {len(rows)}", f"- Complete feature vectors: {len(complete)}",
        f"- Incomplete: {len(rows) - len(complete)}", f"- LOW / MEDIUM / HIGH: {levels['low']} / {levels['medium']} / {levels['high']}",
        f"- MEDIUM+HIGH: {levels['medium'] + levels['high']} ({((levels['medium'] + levels['high']) / len(complete) * 100 if complete else 0):.1f}%)",
        f"- Mean / median score: {(mean(scores) if scores else float('nan')):.3f} / {(median(scores) if scores else float('nan')):.3f}", "",
        "## Events", "",
        "| Event | Reference time | Source | Location | Coordinate precision | Completeness | Score | Level | Notes |", "|---|---|---|---|---|---|---:|---|---|",
    ]
    for row in rows:
        factors = json.loads(row["main_factors"]) if row.get("main_factors") else []
        factor_names = ", ".join(item.get("feature", "") for item in factors if isinstance(item, dict))
        notes = "; ".join(filter(None, [row.get("reference_time_basis", ""), row.get("missing_feature_reason", ""), factor_names]))
        lines.append(f"| {row['event_id']} | {row['evaluation_reference_time']} | {row['source']} ({row['source_type']}) | {row['location']} | {row['coordinate_basis']} | {row['feature_status']} | {float(row['risk_score']):.3f} | {row['risk_level'].upper()} | {notes} |" if row["risk_score"] != "" else f"| {row['event_id']} | {row['evaluation_reference_time']} | {row['source']} ({row['source_type']}) | {row['location']} | {row['coordinate_basis']} | incomplete | — | — | {notes} |")
    lines.extend(["", "## Pre-event trajectories", "", "Trajectories are limited to the two minute-precision Telegram events. Every T-12h/T-6h/T-3h vector is rebuilt as of that timestamp; the event-reference row is the already reconstructed T0 vector. Date-only official reports are excluded.", "", "| Event | Offset | Evaluation time | Score | Level |", "|---|---:|---|---:|---|"])
    for row in trajectories:
        lines.append(f"| {row['original_event_id']} | {row['trajectory_offset_hours']}h | {row['evaluation_reference_time']} | {float(row['risk_score']):.3f} | {row['risk_level'].upper()} |")
    lines.extend(["", "## Interpretation limitations", "", "Date-only official reports use the retained nearest qualifying FIRMS candidate acquisition time as the evaluation reference. This is explicit and does not upgrade source timestamp precision. That candidate is excluded from historical FIRMS-density features. Coordinates are geocoded area/locality references, not verified ignition points. Weather uses UTC observations strictly before each reference time. No post-event FIRMS observation is used as prior-fire context.", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)


def build(*, weather_client: OpenMeteoHistoricalClient | None = None, logger=print) -> list[dict[str, Any]]:
    events = discover_tier_b_events()
    incidents = load_firms_incidents(FIRMS_INPUT)
    feature_rows = reconstruct_features(events, incidents, weather_client=weather_client, logger=logger)
    result_rows = score_rows(feature_rows)
    trajectory_inputs = trajectory_events(events)
    trajectory_feature_rows = reconstruct_features(trajectory_inputs, incidents, weather_client=weather_client, logger=logger) if trajectory_inputs else []
    trajectory_rows = score_rows(trajectory_feature_rows)
    for row in result_rows:
        if row["source_type"] == "verified_telegram":
            trajectory_rows.append({**row, "original_event_id": row["event_id"], "trajectory_offset_hours": 0})
    trajectory_rows.sort(key=lambda row: (row["original_event_id"], int(row["trajectory_offset_hours"])))
    _atomic_csv(FEATURE_OUTPUT, feature_rows)
    _atomic_csv(RESULT_OUTPUT, result_rows)
    if trajectory_rows:
        _atomic_csv(TRAJECTORY_OUTPUT, trajectory_rows)
    write_report(REPORT_OUTPUT, result_rows, trajectory_rows)
    return result_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        rows = build()
    except (CaseStudyError, OSError, ValueError, rasterio.errors.RasterioError) as error:
        print(f"Case-study build failed: {error}")
        return 1
    complete = [row for row in rows if row["risk_score"] != ""]
    print(f"Tier B events: {len(rows)}; complete: {len(complete)}; incomplete: {len(rows) - len(complete)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
