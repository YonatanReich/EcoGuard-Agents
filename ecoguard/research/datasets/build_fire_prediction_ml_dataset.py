"""Combine positive and proxy-negative weather rows into one ML-ready CSV."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from statistics import median
from typing import Any

from ecoguard.research.datasets.build_historical_fire_weather_features import FEATURE_FIELDS
from ecoguard.research.datasets.build_historical_negative_weather_features import (
    OUTPUT_PATH as NEGATIVE_WEATHER_PATH,
)
from ecoguard.paths import GENERATED


POSITIVE_WEATHER_PATH = GENERATED / "historical_fire_weather_features_2023_2026.csv"
OUTPUT_PATH = GENERATED / "fire_prediction_ml_dataset_2023_2026.csv"

PROVENANCE_FIELDS = (
    "official_month_support",
    "official_event_count",
    "firms_candidates_same_settlement_month",
    "ground_truth_status",
    "reference_positive_candidate_id",
    "sample_generation_method",
)
COMMON_FIELDS = (
    "sample_id",
    "sample_type",
    "timestamp",
    "latitude",
    "longitude",
    "settlement",
    "settlement_lamas_code",
    "fire_label",
    "label_source",
    "weather_source",
    "weather_collection_status",
    "weather_error",
)
OUTPUT_FIELDS = COMMON_FIELDS + PROVENANCE_FIELDS + FEATURE_FIELDS
ML_FEATURE_FIELDS = FEATURE_FIELDS

FORBIDDEN_ML_FIELDS = frozenset(
    {
        "max_frp",
        "mean_frp",
        "hotspot_count",
        "confidence",
        "firms_confidence",
        "satellite",
        "satellites",
        "source_product",
        "source_products",
    }
)


class UnifiedDatasetError(RuntimeError):
    """Input schema or unified-dataset validation failure."""


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise UnifiedDatasetError(f"required generated input is missing: {path}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        raise UnifiedDatasetError(f"generated input is malformed: {path}") from None


def _require_schema(rows: list[Mapping[str, Any]], fields: set[str], label: str) -> None:
    if not rows or not fields.issubset(rows[0]):
        raise UnifiedDatasetError(f"{label} input has an incompatible schema")


def positive_row(row: Mapping[str, Any]) -> dict[str, Any]:
    output = {
        "sample_id": row["candidate_id"],
        "sample_type": "positive",
        "timestamp": row["start_timestamp"],
        "latitude": row["centroid_latitude"],
        "longitude": row["centroid_longitude"],
        "settlement": row.get("settlement", ""),
        "settlement_lamas_code": row.get("settlement_lamas_code", ""),
        "fire_label": 1,
        "label_source": "firms_candidate_with_official_month_support",
        "weather_source": row.get("weather_source", ""),
        "weather_collection_status": row.get("weather_collection_status", ""),
        "weather_error": row.get("weather_error", ""),
        "official_month_support": row.get("official_month_support", ""),
        "official_event_count": row.get("official_event_count", ""),
        "firms_candidates_same_settlement_month": row.get(
            "firms_candidates_same_settlement_month", ""
        ),
        "ground_truth_status": row.get("ground_truth_status", ""),
        "reference_positive_candidate_id": "",
        "sample_generation_method": "",
    }
    output.update({field: row.get(field, "") for field in FEATURE_FIELDS})
    return output


def negative_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if str(row.get("fire_label", "")).strip() != "0":
        raise UnifiedDatasetError("negative weather input contains a nonzero fire label")
    output = {
        "sample_id": row["negative_id"],
        "sample_type": "negative",
        "timestamp": row["sample_timestamp"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "settlement": row.get("settlement", ""),
        "settlement_lamas_code": row.get("settlement_lamas_code", ""),
        "fire_label": 0,
        "label_source": "firms_proxy_negative",
        "weather_source": row.get("weather_source", ""),
        "weather_collection_status": row.get("weather_collection_status", ""),
        "weather_error": row.get("weather_error", ""),
        "official_month_support": row.get("official_month_support", ""),
        "official_event_count": "",
        "firms_candidates_same_settlement_month": "",
        "ground_truth_status": "",
        "reference_positive_candidate_id": row.get(
            "reference_positive_candidate_id", ""
        ),
        "sample_generation_method": row.get("sample_generation_method", ""),
    }
    output.update({field: row.get(field, "") for field in FEATURE_FIELDS})
    return output


def combine_datasets(
    positive_rows: list[Mapping[str, Any]], negative_rows: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    positive_required = {
        "candidate_id", "start_timestamp", "centroid_latitude",
        "centroid_longitude", "ground_truth_status", *FEATURE_FIELDS,
    }
    negative_required = {
        "negative_id", "sample_timestamp", "latitude", "longitude",
        "fire_label", *FEATURE_FIELDS,
    }
    _require_schema(positive_rows, positive_required, "positive weather")
    _require_schema(negative_rows, negative_required, "negative weather")
    if any(row.get("ground_truth_status") != "supported" for row in positive_rows):
        raise UnifiedDatasetError("positive input contains a non-supported row")
    combined = [positive_row(row) for row in positive_rows] + [
        negative_row(row) for row in negative_rows
    ]
    combined.sort(key=lambda row: (str(row["timestamp"]), str(row["sample_type"]), str(row["sample_id"])))
    identifiers = [str(row["sample_id"]) for row in combined]
    if len(identifiers) != len(set(identifiers)):
        raise UnifiedDatasetError("unified dataset contains duplicate sample IDs")
    coordinate_times = [
        (str(row["timestamp"]), str(row["latitude"]), str(row["longitude"]))
        for row in combined
    ]
    if len(coordinate_times) != len(set(coordinate_times)):
        raise UnifiedDatasetError(
            "unified dataset contains duplicate timestamp/coordinate rows"
        )
    if set(ML_FEATURE_FIELDS) & FORBIDDEN_ML_FIELDS:
        raise UnifiedDatasetError("ML feature list contains FIRMS detection leakage")
    return combined


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


def summarize_dataset(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    labels = Counter(int(row["fire_label"]) for row in rows)
    null_counts = {}
    numeric_summary = {}
    for field in ML_FEATURE_FIELDS:
        values = []
        missing = 0
        for row in rows:
            value = row.get(field)
            if value in {None, ""}:
                missing += 1
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                missing += 1
        null_counts[field] = missing
        numeric_summary[field] = (
            {"min": min(values), "median": median(values), "max": max(values)}
            if values
            else {"min": None, "median": None, "max": None}
        )
    year_by_class = Counter(
        (str(row["timestamp"])[:4], str(row["sample_type"])) for row in rows
    )
    location_by_class = Counter(
        (
            str(row["sample_type"]),
            "mapped" if row.get("settlement_lamas_code") else "unlocated",
        )
        for row in rows
    )
    identifiers = [str(row["sample_id"]) for row in rows]
    coordinate_times = [
        (str(row["timestamp"]), str(row["latitude"]), str(row["longitude"]))
        for row in rows
    ]
    return {
        "positive_rows": labels[1],
        "negative_rows": labels[0],
        "class_ratio_positive_to_negative": f"{labels[1]}:{labels[0]}",
        "missing_weather_rows": sum(
            any(row.get(field) in {None, ""} for field in ML_FEATURE_FIELDS)
            for row in rows
        ),
        "weather_status": dict(sorted(Counter(str(row["weather_collection_status"]) for row in rows).items())),
        "duplicate_sample_ids": len(identifiers) - len(set(identifiers)),
        "duplicate_timestamp_coordinates": len(coordinate_times) - len(set(coordinate_times)),
        "null_counts": null_counts,
        "numeric_weather_summary": numeric_summary,
        "year_by_class": {
            f"{year}_{sample_type}": count
            for (year, sample_type), count in sorted(year_by_class.items())
        },
        "location_by_class": {
            f"{sample_type}_{status}": count
            for (sample_type, status), count in sorted(location_by_class.items())
        },
    }


def build_unified_dataset(
    *,
    positive_path: Path = POSITIVE_WEATHER_PATH,
    negative_path: Path = NEGATIVE_WEATHER_PATH,
    output_path: Path = OUTPUT_PATH,
) -> list[dict[str, Any]]:
    rows = combine_datasets(load_rows(positive_path), load_rows(negative_path))
    write_output(output_path, rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positives", type=Path, default=POSITIVE_WEATHER_PATH)
    parser.add_argument("--negatives", type=Path, default=NEGATIVE_WEATHER_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    try:
        rows = build_unified_dataset(
            positive_path=args.positives,
            negative_path=args.negatives,
            output_path=args.output,
        )
    except UnifiedDatasetError as error:
        print(f"Unified ML dataset build failed: {error}")
        return 1
    print(json.dumps(summarize_dataset(rows), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
