"""Enrich historical FIRMS proxy negatives with pre-event weather."""

from __future__ import annotations

import argparse
import csv
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from research.datasets.build_historical_fire_weather_features import (
    ARCHIVE_ENDPOINT,
    FEATURE_FIELDS,
    REQUEST_PAUSE_SECONDS,
    SOURCE_NAME,
    HistoricalWeatherError,
    OpenMeteoHistoricalClient,
    ProviderError,
    WeatherCheckpoint,
    checkpoint_configuration,
    compute_features,
    parse_utc_timestamp,
)


INPUT_PATH = Path("data/generated/historical_fire_negative_samples_2023_2026.csv")
OUTPUT_PATH = Path("data/generated/historical_fire_negative_weather_features_2023_2026.csv")
CHECKPOINT_PATH = Path("data/generated/historical_fire_negative_weather_checkpoint")

NEGATIVE_FIELDS = (
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
OUTPUT_FIELDS = NEGATIVE_FIELDS + (
    "weather_source",
    "weather_collection_status",
    "weather_error",
) + FEATURE_FIELDS


def load_negative_samples(path: Path = INPUT_PATH) -> list[dict[str, str]]:
    if not path.exists():
        raise HistoricalWeatherError(f"required generated input is missing: {path}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        raise HistoricalWeatherError(f"generated input is malformed: {path}") from None
    if not rows or not set(NEGATIVE_FIELDS).issubset(rows[0]):
        raise HistoricalWeatherError("negative sample input has an incompatible schema")
    if any(str(row.get("fire_label", "")).strip() != "0" for row in rows):
        raise HistoricalWeatherError("negative sample input contains a nonzero fire label")
    return sorted(rows, key=lambda row: (row["sample_timestamp"], row["negative_id"]))


def checkpoint_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt negative metadata to the existing weather checkpoint identity."""
    return {
        "candidate_id": row["negative_id"],
        "start_timestamp": row["sample_timestamp"],
        "centroid_latitude": row["latitude"],
        "centroid_longitude": row["longitude"],
    }


def build_negative_feature_row(
    negative: Mapping[str, Any], weather: Mapping[str, Any]
) -> dict[str, Any]:
    features, status = compute_features(
        weather, parse_utc_timestamp(negative["sample_timestamp"])
    )
    row = {field: negative.get(field, "") for field in NEGATIVE_FIELDS}
    row.update(
        {
            "fire_label": 0,
            "weather_source": SOURCE_NAME,
            "weather_collection_status": status,
            "weather_error": "",
        }
    )
    row.update(features)
    return row


def failed_negative_feature_row(
    negative: Mapping[str, Any], category: str
) -> dict[str, Any]:
    row = {field: negative.get(field, "") for field in NEGATIVE_FIELDS}
    row.update(
        {
            "fire_label": 0,
            "weather_source": SOURCE_NAME,
            "weather_collection_status": "failed",
            "weather_error": category,
        }
    )
    row.update({field: None for field in FEATURE_FIELDS})
    return row


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


def format_progress(
    completed: int,
    total: int,
    negative: Mapping[str, Any],
    cached: int,
    elapsed: float,
) -> str:
    percentage = completed / total * 100 if total else 100.0
    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"Progress: {completed} / {total} negatives ({percentage:.1f}%)\n"
        f"Negative: {negative.get('negative_id', '')}\n"
        f"Timestamp: {negative.get('sample_timestamp', '')}\n"
        f"Weather rows cached: {cached}\n"
        f"Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}"
    )


def build_negative_weather_features(
    *,
    input_path: Path = INPUT_PATH,
    output_path: Path = OUTPUT_PATH,
    checkpoint_path: Path = CHECKPOINT_PATH,
    client: OpenMeteoHistoricalClient | None = None,
    progress_logger: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    request_pause_seconds: float = REQUEST_PAUSE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    negatives = load_negative_samples(input_path)
    provider = client or OpenMeteoHistoricalClient(endpoint=ARCHIVE_ENDPOINT)
    checkpoint = WeatherCheckpoint(
        checkpoint_path, checkpoint_configuration(provider.endpoint)
    )
    checkpoint.initialize()
    started = clock()
    rows = []
    cached_count = 0
    for index, negative in enumerate(negatives, start=1):
        identity = checkpoint_candidate(negative)
        weather = checkpoint.load(identity)
        if weather is None:
            try:
                event_time = parse_utc_timestamp(negative["sample_timestamp"])
                weather = provider.fetch(
                    float(negative["latitude"]),
                    float(negative["longitude"]),
                    event_time,
                )
                checkpoint.save(identity, weather)
                cached_count += 1
                rows.append(build_negative_feature_row(negative, weather))
            except ProviderError as error:
                rows.append(failed_negative_feature_row(negative, error.category))
            if request_pause_seconds and index < len(negatives):
                sleep(request_pause_seconds)
        else:
            cached_count += 1
            rows.append(build_negative_feature_row(negative, weather))
        progress_logger(
            format_progress(
                index, len(negatives), negative, cached_count, clock() - started
            )
        )
    rows.sort(key=lambda row: (str(row["sample_timestamp"]), str(row["negative_id"])))
    write_output(output_path, rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--checkpoint-dir", type=Path, default=CHECKPOINT_PATH)
    args = parser.parse_args()
    try:
        rows = build_negative_weather_features(
            input_path=args.input,
            output_path=args.output,
            checkpoint_path=args.checkpoint_dir,
        )
    except HistoricalWeatherError as error:
        print(f"Historical negative weather build failed: {error}")
        return 1
    statuses: dict[str, int] = {}
    for row in rows:
        status = str(row["weather_collection_status"])
        statuses[status] = statuses.get(status, 0) + 1
    print(f"Historical negative weather rows: {len(rows)}; statuses: {statuses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
