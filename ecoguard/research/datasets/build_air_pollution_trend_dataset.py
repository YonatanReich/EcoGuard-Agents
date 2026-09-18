"""Build deterministic chronological Trend ML shards from the existing cache.

This is an offline research builder, not a downloader or runtime.  It processes
one station/channel/pollutant identity at a time and never samples rows.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from ecoguard.paths import GENERATED
from ecoguard.shared.air_pollution_history import (
    AirPollutionSeriesIdentity,
    HistoricalAirPollutionObservation,
    discover_history_series,
    read_history_month,
)
from ecoguard.shared.air_pollution_trend_features import (
    FEATURE_COLUMNS,
    FUTURE_WINDOW_MINUTES,
    LOOKBACK_MINUTES,
    PROVIDER_TIMEZONE,
    ResearchSplitPolicy,
    TREND_FEATURE_POLICY_VERSION,
    TREND_TARGET_VERSION,
    build_trend_example,
)

DATASET_VERSION = "air-pollution-trend-dataset-v1"
DEFAULT_CACHE = (
    Path(__file__).resolve().parents[3]
    / "venv/phase2-output/air-pollution-five-minute-cache"
)
DEFAULT_OUTPUT = GENERATED / "ml" / "air_pollution_trend" / "dataset-v1"
SUPPORTED_POLLUTANTS = ("NO2", "O3", "PM10", "PM2.5", "SO2")
CSV_COLUMNS = (
    "dataset_version", "feature_policy_version", "target_version", "split",
    "station_id", "channel_id", "pollutant", "observed_at", "unit",
    *FEATURE_COLUMNS,
    "future_concentration", "delta_30", "target_contributing_timestamps",
    "target_contributing_offsets_minutes", "epsilon", "trend_label",
)


class DatasetBuildError(RuntimeError):
    """The requested cache selection cannot produce an auditable dataset."""


def _slug(value: str) -> str:
    return value.lower().replace(".", "_")


def _identity_from_directory(files: list[Path]) -> AirPollutionSeriesIdentity:
    directory = files[0].parent.name
    station_directory = files[0].parent.parent.name
    if not directory.startswith("channel_") or not station_directory.startswith("station_"):
        raise DatasetBuildError(f"unexpected cache directory: {files[0].parent}")
    remainder = directory.removeprefix("channel_")
    for pollutant in sorted(SUPPORTED_POLLUTANTS, key=len, reverse=True):
        suffix = "_" + _slug(pollutant)
        if remainder.endswith(suffix):
            channel_id = remainder[:-len(suffix)]
            if channel_id:
                return AirPollutionSeriesIdentity(
                    station_id=station_directory.removeprefix("station_"),
                    channel_id=channel_id,
                    pollutant=pollutant,
                )
    raise DatasetBuildError(f"cannot parse cache identity: {files[0].parent}")


def select_series(
    cache_dir: Path,
    *,
    pollutant: str | None = None,
    station_id: str | None = None,
    channel_id: str | None = None,
    max_series: int | None = None,
) -> tuple[list[tuple[AirPollutionSeriesIdentity, list[Path]]], int]:
    discovered = [
        (_identity_from_directory(files), files)
        for files in discover_history_series(cache_dir)
    ]
    selected = [
        (identity, files)
        for identity, files in discovered
        if (pollutant is None or identity.pollutant == pollutant)
        and (station_id is None or identity.station_id == station_id)
        and (channel_id is None or identity.channel_id == channel_id)
    ]
    selected.sort(key=lambda item: item[0])
    matched_before_limit = len(selected)
    if max_series is not None:
        selected = selected[:max_series]
    return selected, matched_before_limit


def _month_key(path: Path) -> tuple[int, int]:
    try:
        year, month = path.name[:7].split("-")
        return int(year), int(month)
    except (TypeError, ValueError):
        raise DatasetBuildError(f"invalid cache month filename: {path.name}") from None


def _wanted_cache_files(
    files: list[Path], years: set[int], month_filter: int | None
) -> list[Path]:
    wanted_candidate_months = {
        (year, month)
        for year in years
        for month in ([month_filter] if month_filter is not None else range(1, 13))
    }
    wanted_with_halo = set(wanted_candidate_months)
    for year, month in wanted_candidate_months:
        first = datetime(year, month, 1, tzinfo=PROVIDER_TIMEZONE)
        before = first - timedelta(minutes=LOOKBACK_MINUTES)
        if month == 12:
            after = datetime(year + 1, 1, 1, tzinfo=PROVIDER_TIMEZONE)
        else:
            after = datetime(year, month + 1, 1, tzinfo=PROVIDER_TIMEZONE)
        after += timedelta(minutes=FUTURE_WINDOW_MINUTES)
        wanted_with_halo.add((before.year, before.month))
        wanted_with_halo.add((after.year, after.month))
    return [path for path in files if _month_key(path) in wanted_with_halo]


def _open_deterministic_gzip_text(path: Path):
    raw = path.open("wb")
    compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
    return io.TextIOWrapper(compressed, encoding="utf-8", newline="")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_epsilons(values: Iterable[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in values:
        try:
            pollutant, raw = item.split("=", 1)
            epsilon = float(raw)
        except (TypeError, ValueError):
            raise DatasetBuildError("--epsilon must use POLLUTANT=POSITIVE_NUMBER") from None
        if pollutant not in SUPPORTED_POLLUTANTS or epsilon <= 0:
            raise DatasetBuildError("--epsilon pollutant is unsupported or value is not positive")
        result[pollutant] = epsilon
    return result


def _candidate_period(year: int, month: int | None) -> tuple[datetime, datetime]:
    start = datetime(year, month or 1, 1, tzinfo=PROVIDER_TIMEZONE)
    if month is None:
        end = datetime(year + 1, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    elif month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=PROVIDER_TIMEZONE)
    else:
        end = datetime(year, month + 1, 1, tzinfo=PROVIDER_TIMEZONE)
    return start, end


def _gap_report(
    observations: list[HistoricalAirPollutionObservation], start: datetime, end: datetime
) -> dict[str, int | float | None]:
    selected = [item for item in observations if start <= item.observed_at < end]
    gap_minutes = [
        (right.observed_at - left.observed_at).total_seconds() / 60.0
        for left, right in zip(selected, selected[1:])
    ]
    expected_slots = int((end - start).total_seconds() // 300)
    return {
        "expected_slots": expected_slots,
        "accepted_observations": len(selected),
        "absent_or_rejected_slots": expected_slots - len(selected),
        "gaps_over_five_minutes": sum(value > 5 for value in gap_minutes),
        "missing_slots_inside_gaps": sum(max(0, int(value // 5) - 1) for value in gap_minutes),
        "maximum_gap_minutes": max(gap_minutes) if gap_minutes else None,
    }


def build_dataset(
    *,
    cache_dir: Path,
    output_dir: Path,
    pollutant: str | None = None,
    station_id: str | None = None,
    channel_id: str | None = None,
    years: set[int] | None = None,
    month_filter: int | None = None,
    max_series: int | None = None,
    epsilons: dict[str, float] | None = None,
    epsilon_version: str = "caller-supplied-v1",
) -> dict[str, Any]:
    years = years or set(range(2021, 2026))
    epsilons = epsilons or {}
    if not years or not years <= set(range(2021, 2026)):
        raise DatasetBuildError("years must be within 2021-2025")
    if month_filter is not None and not 1 <= month_filter <= 12:
        raise DatasetBuildError("month must be between 1 and 12")
    if max_series is not None and max_series < 1:
        raise DatasetBuildError("max-series must be positive")
    if output_dir.exists() and any(output_dir.rglob("*")):
        raise DatasetBuildError(f"output directory is not empty: {output_dir}")

    selected, matched_before_limit = select_series(
        cache_dir,
        pollutant=pollutant,
        station_id=station_id,
        channel_id=channel_id,
        max_series=max_series,
    )
    if not selected:
        raise DatasetBuildError("no cache series matched the filters")
    output_dir.mkdir(parents=True, exist_ok=True)
    split_policy = ResearchSplitPolicy()
    totals: Counter[str] = Counter()
    exclusions: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    negative = Counter()
    input_files: list[dict[str, Any]] = []
    output_files: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []

    for expected_identity, files in selected:
        wanted = _wanted_cache_files(files, years, month_filter)
        observations: list[HistoricalAirPollutionObservation] = []
        quality: Counter[str] = Counter()
        units: set[str] = set()
        for path in wanted:
            month = read_history_month(path)
            if month.identity != expected_identity:
                raise DatasetBuildError(f"cache directory/header identity mismatch: {path}")
            observations.extend(month.observations)
            quality.update(month.quality_summary)
            units.update(item.unit for item in month.observations)
            input_files.append({
                "path": str(path.relative_to(cache_dir)).replace("\\", "/"),
                "content_sha256": month.content_sha256,
                "point_count": month.point_count,
                "accepted_unique_observations": len(month.observations),
            })
        observations.sort(key=lambda item: item.observed_at)
        if len(units) != 1:
            raise DatasetBuildError(
                f"series does not have exactly one canonical unit: {expected_identity}"
            )
        timestamps = [item.observed_at for item in observations]

        for year in sorted(years):
            start, end = _candidate_period(year, month_filter)
            candidates = [item for item in observations if start <= item.observed_at < end]
            if not candidates:
                coverage.append({
                    "station_id": expected_identity.station_id,
                    "channel_id": expected_identity.channel_id,
                    "pollutant": expected_identity.pollutant,
                    "year": year,
                    "candidate_observations": 0,
                    "included_examples": 0,
                    "gap_report": _gap_report(observations, start, end),
                })
                continue
            part_dir = (
                output_dir
                / f"pollutant={_slug(expected_identity.pollutant)}"
                / f"year={year}"
            )
            part_dir.mkdir(parents=True, exist_ok=True)
            part_path = part_dir / (
                f"station_{expected_identity.station_id}_"
                f"channel_{expected_identity.channel_id}.csv.gz"
            )
            included = 0
            with _open_deterministic_gzip_text(part_path) as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
                writer.writeheader()
                for current in candidates:
                    totals["candidate_current_observations"] += 1
                    split, split_reason = split_policy.split_for_example(current.observed_at)
                    if split_reason is not None:
                        exclusions[split_reason] += 1
                        continue
                    lower = bisect.bisect_left(
                        timestamps, current.observed_at - timedelta(minutes=LOOKBACK_MINUTES)
                    )
                    upper = bisect.bisect_right(
                        timestamps, current.observed_at + timedelta(minutes=FUTURE_WINDOW_MINUTES)
                    )
                    example = build_trend_example(observations[lower:upper], current.observed_at)
                    if example is None:
                        exclusions["insufficient_future_target_readings"] += 1
                        continue
                    epsilon = epsilons.get(expected_identity.pollutant)
                    label = ""
                    if epsilon is not None:
                        label = (
                            "RISING" if example.target.delta_30 > epsilon
                            else "FALLING" if example.target.delta_30 < -epsilon
                            else "STABLE"
                        )
                        classes[label] += 1
                        totals["labeled_examples"] += 1
                    else:
                        totals["unlabeled_examples"] += 1
                    row: dict[str, Any] = {
                        "dataset_version": DATASET_VERSION,
                        "feature_policy_version": TREND_FEATURE_POLICY_VERSION,
                        "target_version": TREND_TARGET_VERSION,
                        "split": split,
                        "station_id": expected_identity.station_id,
                        "channel_id": expected_identity.channel_id,
                        "pollutant": expected_identity.pollutant,
                        "observed_at": current.observed_at.isoformat(),
                        "unit": current.unit,
                        **example.features,
                        "future_concentration": example.target.future_concentration,
                        "delta_30": example.target.delta_30,
                        "target_contributing_timestamps": ";".join(
                            value.isoformat() for value in example.target.contributing_timestamps
                        ),
                        "target_contributing_offsets_minutes": ";".join(
                            str(value) for value in example.target.contributing_offsets_minutes
                        ),
                        "epsilon": "" if epsilon is None else epsilon,
                        "trend_label": label,
                    }
                    writer.writerow(row)
                    included += 1
                    totals["included_examples"] += 1
                    if current.value < 0:
                        negative["included_negative_current_values"] += 1
            if included == 0:
                part_path.unlink()
            else:
                output_files.append({
                    "path": str(part_path.relative_to(output_dir)).replace("\\", "/"),
                    "sha256": _sha256(part_path),
                    "row_count": included,
                    "station_id": expected_identity.station_id,
                    "channel_id": expected_identity.channel_id,
                    "pollutant": expected_identity.pollutant,
                    "year": year,
                })
            candidate_negatives = sum(item.value < 0 for item in candidates)
            negative["accepted_negative_values_in_candidate_periods"] += candidate_negatives
            coverage.append({
                "station_id": expected_identity.station_id,
                "channel_id": expected_identity.channel_id,
                "pollutant": expected_identity.pollutant,
                "year": year,
                "candidate_observations": len(candidates),
                "included_examples": included,
                "gap_report": _gap_report(observations, start, end),
            })
        totals.update({f"reader_{key}": value for key, value in quality.items()})

    totals["excluded_examples"] = sum(exclusions.values())
    manifest = {
        "dataset_version": DATASET_VERSION,
        "deterministic": True,
        "sampling_or_downsampling": False,
        "feature_policy_version": TREND_FEATURE_POLICY_VERSION,
        "target_version": TREND_TARGET_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "csv_columns": list(CSV_COLUMNS),
        "target": {
            "future_offsets_minutes": [25, 30, 35],
            "minimum_future_readings": 2,
            "aggregation": "median",
            "delta": "future_concentration_minus_current_concentration",
        },
        "split_policy": split_policy.to_dict(),
        "filters": {
            "pollutant": pollutant,
            "station_id": station_id,
            "channel_id": channel_id,
            "years": sorted(years),
            "month": month_filter,
        },
        "development_limit": {
            "active": max_series is not None or month_filter is not None,
            "max_series": max_series,
            "month_filter": month_filter,
            "matched_series_before_limit": matched_before_limit,
            "processed_series": len(selected),
        },
        "stability_bands": {
            key: {
                "epsilon": value,
                "version": epsilon_version,
                "source": "caller_supplied_frozen_configuration",
                "independent_of_p95": True,
            }
            for key, value in sorted(epsilons.items())
        },
        "counts": dict(sorted(totals.items())),
        "exclusion_reason_counts": dict(sorted(exclusions.items())),
        "class_counts": {
            label: classes[label] for label in ("RISING", "STABLE", "FALLING")
        } if epsilons else {},
        "negative_value_report": dict(sorted(negative.items())),
        "series_year_coverage": coverage,
        "input_files": sorted(input_files, key=lambda item: item["path"]),
        "output_files": sorted(output_files, key=lambda item: item["path"]),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pollutant", choices=SUPPORTED_POLLUTANTS)
    parser.add_argument("--station-id")
    parser.add_argument("--channel-id")
    parser.add_argument("--year", action="append", type=int)
    parser.add_argument("--month", type=int, help="development-only candidate-month filter")
    parser.add_argument(
        "--max-series", type=int,
        help="development-only deterministic series limit",
    )
    parser.add_argument("--epsilon", action="append", default=[], metavar="POLLUTANT=VALUE")
    parser.add_argument("--epsilon-version", default="caller-supplied-v1")
    args = parser.parse_args(argv)
    manifest = build_dataset(
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        pollutant=args.pollutant,
        station_id=args.station_id,
        channel_id=args.channel_id,
        years=set(args.year) if args.year else None,
        month_filter=args.month,
        max_series=args.max_series,
        epsilons=_parse_epsilons(args.epsilon),
        epsilon_version=args.epsilon_version,
    )
    print(json.dumps({
        "output_dir": str(args.output_dir),
        "counts": manifest["counts"],
        "exclusions": manifest["exclusion_reason_counts"],
        "class_counts": manifest["class_counts"],
        "output_files": len(manifest["output_files"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
