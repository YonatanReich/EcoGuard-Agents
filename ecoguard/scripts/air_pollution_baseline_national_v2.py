"""Building the national air-quality baselines.

Downloads years of history for every station and pollutant, groups it by season
and hour, and writes one profile per series. Those profiles are what makes
"unusual for here, at this time of year" answerable at all.

Long-running and run rarely: a station is sampled first to check it is worth
downloading in full."""

from __future__ import annotations

import argparse
import asyncio
import calendar
import csv
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE2_DEPS = REPO_ROOT / "venv" / "phase2-deps"
if PHASE2_DEPS.exists():
    sys.path.insert(0, str(PHASE2_DEPS))

import aiohttp  # noqa: E402
from air_sviva_api.client import SvivaAirClient  # noqa: E402

TARGET_POLLUTANTS = {"SO2", "NO2", "O3", "PM10", "PM2.5"}
SENTINELS = {-9999, -9999.0}

# Baselines are meant to describe a fixed monitoring location. These names are
# conservatively excluded by default. Use --include-mobile if you intentionally
# want to inspect them.
MOBILE_NAME_MARKERS = (
    "ניידת",
    "קרון",
)


@dataclass(frozen=True)
class Target:
    station_id: int
    station_name: str
    channel_id: int
    pollutant: str
    metadata_unit: str | None
    active: bool | None


def slug(text: str) -> str:
    """A name safe to use as a filename."""
    out = []
    for ch in text:
        out.append(ch if (ch.isalnum() or ch in "-_") else "_")
    return "".join(out).strip("_") or "unknown"


def normalize_pollutant(name: Any) -> str:
    """One spelling per pollutant."""
    p = str(name or "").upper().replace(" ", "")
    if p in {"PM2_5", "PM25"}:
        return "PM2.5"
    return p


def percentile(values: list[float], p: float) -> float | None:
    """The value below which this share of readings falls."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    pos = (len(xs) - 1) * (p / 100.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(xs[lo])
    w = pos - lo
    return float(xs[lo] * (1 - w) + xs[hi] * w)


def r4(x: float | None) -> float | None:
    """A number at storage precision, or None when there is none."""
    return None if x is None else round(float(x), 4)


async def discover_targets(client: SvivaAirClient) -> list[Target]:
    """Every station and pollutant a baseline can be built for."""
    regions = await client.get_regions()
    found: dict[tuple[int, int, str], Target] = {}

    for region in regions:
        for station in (getattr(region, "stations", None) or []):
            station_id = getattr(station, "station_id", None)
            station_name = getattr(station, "name", None) or f"station_{station_id}"
            if station_id is None:
                continue

            for mon in (getattr(station, "monitors", None) or []):
                pollutant = normalize_pollutant(getattr(mon, "name", ""))
                if pollutant not in TARGET_POLLUTANTS:
                    continue

                channel_id = getattr(mon, "channel_id", None)
                if channel_id is None:
                    continue

                target = Target(
                    station_id=int(station_id),
                    station_name=str(station_name),
                    channel_id=int(channel_id),
                    pollutant=pollutant,
                    metadata_unit=getattr(mon, "units", None),
                    active=getattr(mon, "active", None),
                )
                found[(target.station_id, target.channel_id, target.pollutant)] = target

    return sorted(found.values(), key=lambda t: (t.station_id, t.channel_id, t.pollutant))


def exclusion_reason(target: Target, include_mobile: bool, include_inactive: bool) -> str | None:
    """Why this station is being skipped, or None when it is not."""
    if not include_inactive and target.active is False:
        return "inactive_monitor"

    if not include_mobile:
        for marker in MOBILE_NAME_MARKERS:
            if marker in target.station_name:
                return f"mobile_or_temporary_name:{marker}"

    # A textual "not active" signal is treated conservatively even when monitor
    # metadata itself says active=True.
    if "לא פעילה" in target.station_name or "לא פעיל" in target.station_name:
        return "station_name_marks_inactive"

    return None


async def fetch_range(
    client: SvivaAirClient,
    target: Target,
    start: date,
    end: date,
    retries: int,
    retry_backoff_seconds: float,
) -> Any:
    """One station's readings between two dates."""
    for attempt in range(1, retries + 1):
        try:
            return await client.get_station_average(
                target.station_id,
                channel_id=target.channel_id,
                from_date=start,
                to_date=end,
            )
        except Exception:
            if attempt >= retries:
                raise
            await asyncio.sleep(retry_backoff_seconds * attempt)
    raise RuntimeError("unreachable")


def extract_hourly(
    response: Any,
    target: Target,
    min_valid_points_per_hour: int,
) -> tuple[list[dict[str, Any]], dict[str, int], set[str]]:
    """The hourly readings out of a provider response."""
    by_hour: dict[tuple[int, int, int, int], dict[str, float]] = defaultdict(dict)
    units: set[str] = set()
    counters = {
        "api_points": 0,
        "matching_channel_points": 0,
        "valid_5min_points": 0,
        "invalid_or_sentinel_points": 0,
        "accepted_hourly_values": 0,
        "rejected_incomplete_hours": 0,
    }

    for point in response.data:
        d = point.to_dict() if hasattr(point, "to_dict") else vars(point)
        ts = d.get("datetime")
        counters["api_points"] += 1
        if not ts:
            continue

        # Preserve provider timestamp semantics exactly as supplied.
        source_dt = datetime.fromisoformat(str(ts))

        for ch in (d.get("channels") or []):
            if ch.get("id") != target.channel_id:
                continue
            if normalize_pollutant(ch.get("name")) not in {"", target.pollutant}:
                continue

            counters["matching_channel_points"] += 1
            value = ch.get("value")
            if ch.get("valid") is not True or value is None or value in SENTINELS:
                counters["invalid_or_sentinel_points"] += 1
                continue

            try:
                fv = float(value)
            except (TypeError, ValueError):
                counters["invalid_or_sentinel_points"] += 1
                continue

            if not math.isfinite(fv):
                counters["invalid_or_sentinel_points"] += 1
                continue

            unit = ch.get("units")
            if unit:
                units.add(str(unit))

            counters["valid_5min_points"] += 1
            key = (source_dt.year, source_dt.month, source_dt.day, source_dt.hour)
            by_hour[key][str(ts)] = fv

    rows: list[dict[str, Any]] = []
    for (year, month, day, hour), ts_values in by_hour.items():
        vals = list(ts_values.values())
        if len(vals) < min_valid_points_per_hour:
            counters["rejected_incomplete_hours"] += 1
            continue
        rows.append(
            {
                "year": year,
                "month": month,
                "day": day,
                "hour": hour,
                "value": statistics.fmean(vals),
            }
        )
        counters["accepted_hourly_values"] += 1

    return rows, counters, units


def choose_preflight_years(start_year: int, end_year: int) -> list[int]:
    """The years to sample first, to check a station is worth downloading in full."""
    years = list(range(start_year, end_year + 1))
    if len(years) <= 3:
        return years
    # Spread the probes across the training interval.
    mid = years[len(years) // 2]
    return sorted({years[0], mid, years[-1]})


async def preflight_target(
    client: SvivaAirClient,
    target: Target,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """
    For each of 3 representative years:
      try Jan 15 first;
      if weak, try Jul 15.

    A year is considered present when one probe day yields at least
    --preflight-min-hourly accepted hourly values.
    """
    probe_years = choose_preflight_years(args.start_year, args.end_year)
    year_results: list[dict[str, Any]] = []
    observed_units: set[str] = set()

    for year in probe_years:
        year_ok = False
        attempts: list[dict[str, Any]] = []

        for month in (1, 7):
            last_day = calendar.monthrange(year, month)[1]
            probe_day = date(year, month, min(15, last_day))

            try:
                response = await fetch_range(
                    client,
                    target,
                    probe_day,
                    probe_day,
                    retries=args.retries,
                    retry_backoff_seconds=args.retry_backoff,
                )
                _rows, counters, units = extract_hourly(
                    response,
                    target,
                    min_valid_points_per_hour=args.min_valid_per_hour,
                )
                observed_units.update(units)

                accepted = counters["accepted_hourly_values"]
                attempts.append(
                    {
                        "date": probe_day.isoformat(),
                        "api_points": counters["api_points"],
                        "valid_5min_points": counters["valid_5min_points"],
                        "accepted_hourly_values": accepted,
                    }
                )

                if accepted >= args.preflight_min_hourly:
                    year_ok = True
                    break

            except Exception as exc:
                attempts.append(
                    {
                        "date": probe_day.isoformat(),
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:200],
                    }
                )

            if args.request_delay > 0:
                await asyncio.sleep(args.request_delay)

        year_results.append(
            {
                "year": year,
                "passed": year_ok,
                "attempts": attempts,
            }
        )

    passed_years = [r["year"] for r in year_results if r["passed"]]
    unit_conflict = len(observed_units) > 1
    passed = (
        len(passed_years) >= args.preflight_min_years
        and not unit_conflict
    )

    if unit_conflict:
        reason = "unit_conflict"
    elif len(passed_years) < args.preflight_min_years:
        reason = "insufficient_preflight_years"
    else:
        reason = "passed"

    return {
        "passed": passed,
        "reason": reason,
        "probe_years": probe_years,
        "passed_years": passed_years,
        "observed_units": sorted(observed_units),
        "year_results": year_results,
    }


async def fetch_month(
    client: SvivaAirClient,
    target: Target,
    year: int,
    month: int,
    args: argparse.Namespace,
) -> Any:
    """One station's readings for one month."""
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return await fetch_range(
        client,
        target,
        start,
        end,
        retries=args.retries,
        retry_backoff_seconds=args.retry_backoff,
    )


def build_buckets(
    hourly_rows: list[dict[str, Any]],
    min_distinct_years_per_bucket: int,
    min_distinct_days_per_bucket: int,
) -> list[dict[str, Any]]:
    """Group readings by season and hour, which is what a baseline compares against."""
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in hourly_rows:
        grouped[(row["month"], row["hour"])].append(row)

    buckets: list[dict[str, Any]] = []

    for month in range(1, 13):
        for hour in range(24):
            rows = grouped.get((month, hour), [])
            values = [r["value"] for r in rows]
            years = sorted({r["year"] for r in rows})
            days = {
                f'{r["year"]:04d}-{r["month"]:02d}-{r["day"]:02d}'
                for r in rows
            }
            enough = (
                len(years) >= min_distinct_years_per_bucket
                and len(days) >= min_distinct_days_per_bucket
            )

            item: dict[str, Any] = {
                "month": month,
                "hour": hour,
                "status": "ok" if enough else "insufficient_history",
                "hourly_sample_count": len(values),
                "distinct_year_count": len(years),
                "distinct_day_count": len(days),
                "years_present": years,
            }

            if values:
                median = statistics.median(values)
                deviations = [abs(v - median) for v in values]
                item.update(
                    {
                        "mean": r4(statistics.fmean(values)),
                        "median": r4(median),
                        "std": r4(statistics.stdev(values) if len(values) > 1 else 0.0),
                        "mad": r4(statistics.median(deviations)),
                        "p05": r4(percentile(values, 5)),
                        "p25": r4(percentile(values, 25)),
                        "p75": r4(percentile(values, 75)),
                        "p95": r4(percentile(values, 95)),
                    }
                )

            buckets.append(item)

    return buckets


def profile_path(profiles_dir: Path, target: Target, args: argparse.Namespace) -> Path:
    """Where one station's baseline is written."""
    name = (
        f"station_{target.station_id}_channel_{target.channel_id}_"
        f"{slug(target.pollutant.lower())}_{args.start_year}_{args.end_year}.json"
    )
    return profiles_dir / name


async def build_full_profile(
    client: SvivaAirClient,
    target: Target,
    preflight: dict[str, Any],
    args: argparse.Namespace,
    profiles_dir: Path,
) -> dict[str, Any]:
    """Download a station's history and build its baseline."""
    out = profile_path(profiles_dir, target, args)

    if out.exists() and not args.force:
        old = json.loads(out.read_text(encoding="utf-8"))
        return {
            "station_id": target.station_id,
            "station_name": target.station_name,
            "channel_id": target.channel_id,
            "pollutant": target.pollutant,
            "status": old.get("profile_status", "completed"),
            "preflight": "passed",
            "skipped_existing": True,
            "unit": old.get("historical_unit"),
            "ok_buckets": old.get("coverage_summary", {}).get("ok_buckets"),
            "total_hourly_values": old.get("quality_summary", {}).get("accepted_hourly_values"),
            "profile_file": str(out),
            "error": None,
        }

    all_hourly: list[dict[str, Any]] = []
    all_units: set[str] = set()
    total = defaultdict(int)
    month_errors: list[dict[str, Any]] = []

    for year in range(args.start_year, args.end_year + 1):
        for month in range(1, 13):
            try:
                response = await fetch_month(client, target, year, month, args)
                rows, counters, units = extract_hourly(
                    response,
                    target,
                    min_valid_points_per_hour=args.min_valid_per_hour,
                )
                all_hourly.extend(rows)
                all_units.update(units)
                for k, v in counters.items():
                    total[k] += v

                print(
                    f"    {year}-{month:02d} "
                    f"valid5m={counters['valid_5min_points']} "
                    f"hourly={counters['accepted_hourly_values']}"
                )
            except Exception as exc:
                month_errors.append(
                    {
                        "year": year,
                        "month": month,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:300],
                    }
                )
                print(f"    {year}-{month:02d} ERROR {type(exc).__name__}")

            if args.request_delay > 0:
                await asyncio.sleep(args.request_delay)

    unit_conflict = len(all_units) > 1
    historical_unit = next(iter(all_units), None) if len(all_units) == 1 else None

    if unit_conflict:
        buckets: list[dict[str, Any]] = []
        status = "unit_conflict"
    else:
        buckets = build_buckets(
            all_hourly,
            args.min_years_per_bucket,
            args.min_days_per_bucket,
        )
        ok_buckets = sum(b["status"] == "ok" for b in buckets)

        if total["accepted_hourly_values"] == 0:
            status = "insufficient_history"
        elif ok_buckets == 288:
            status = "ok"
        elif ok_buckets > 0:
            status = "partial_coverage"
        else:
            status = "insufficient_history"

    ok_buckets = sum(b.get("status") == "ok" for b in buckets)

    payload = {
        "schema_version": "air-pollution-national-baseline-v2",
        "profile_status": status,
        "source": "Israel Ministry of Environmental Protection / Envista",
        "station": {"id": target.station_id, "name": target.station_name},
        "channel_id": target.channel_id,
        "pollutant": target.pollutant,
        "metadata_unit": target.metadata_unit,
        "historical_unit": historical_unit,
        "historical_units_observed": sorted(all_units),
        "monitor_active_metadata": target.active,
        "training_period": {
            "start_year": args.start_year,
            "end_year": args.end_year,
        },
        "preflight": preflight,
        "time_semantics": {
            "rule": "Use provider timestamps as returned; no Asia/Jerusalem DST conversion."
        },
        "hourly_aggregation": {
            "source_resolution_minutes": 5,
            "method": "arithmetic_mean_of_valid_unique_measurements",
            "min_valid_points_per_hour": args.min_valid_per_hour,
        },
        "coverage_policy": {
            "min_distinct_years_per_bucket": args.min_years_per_bucket,
            "min_distinct_days_per_bucket": args.min_days_per_bucket,
        },
        "quality_summary": dict(total),
        "coverage_summary": {
            "ok_buckets": ok_buckets,
            "total_buckets": 288,
            "ok_percent": round(ok_buckets / 288 * 100, 2),
        },
        "month_fetch_errors": month_errors,
        "buckets": buckets,
    }

    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "station_id": target.station_id,
        "station_name": target.station_name,
        "channel_id": target.channel_id,
        "pollutant": target.pollutant,
        "status": status,
        "preflight": "passed",
        "skipped_existing": False,
        "unit": historical_unit,
        "ok_buckets": ok_buckets,
        "total_hourly_values": total["accepted_hourly_values"],
        "profile_file": str(out),
        "error": f"{len(month_errors)} month fetch errors" if month_errors else None,
    }


def write_json(path: Path, payload: Any) -> None:
    """Write a JSON file."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Write a CSV file."""
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) for c in columns})


async def main() -> None:
    """Build the national baselines from the command line."""
    parser = argparse.ArgumentParser()

    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--end-year", type=int, default=2025)

    parser.add_argument("--min-valid-per-hour", type=int, default=9)
    parser.add_argument("--min-years-per-bucket", type=int, default=3)
    parser.add_argument("--min-days-per-bucket", type=int, default=30)

    parser.add_argument(
        "--preflight-min-years",
        type=int,
        default=3,
        help="Minimum representative years that must pass preflight.",
    )
    parser.add_argument(
        "--preflight-min-hourly",
        type=int,
        default=12,
        help="Minimum accepted hourly values on a probe day for that year to pass.",
    )

    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff", type=float, default=1.0)
    parser.add_argument("--request-delay", type=float, default=0.05)

    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--station-id", type=int, default=None)
    parser.add_argument("--pollutant", choices=sorted(TARGET_POLLUTANTS), default=None)

    parser.add_argument("--include-mobile", action="store_true")
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run discovery/filtering/preflight only. Do not download full histories.",
    )
    parser.add_argument("--force", action="store_true")

    args = parser.parse_args()

    if args.end_year < args.start_year:
        raise SystemExit("--end-year must be >= --start-year")

    output_dir = REPO_ROOT / "venv" / "phase2-output" / "national-baseline-v2"
    profiles_dir = output_dir / "profiles"
    output_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)

    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        client = SvivaAirClient(session)
        await client.generate_token()

        discovered = await discover_targets(client)

        if args.station_id is not None:
            discovered = [t for t in discovered if t.station_id == args.station_id]
        if args.pollutant is not None:
            discovered = [t for t in discovered if t.pollutant == args.pollutant]

        exclusions: list[dict[str, Any]] = []
        targets: list[Target] = []
        for t in discovered:
            reason = exclusion_reason(t, args.include_mobile, args.include_inactive)
            if reason:
                exclusions.append(
                    {
                        "station_id": t.station_id,
                        "station_name": t.station_name,
                        "channel_id": t.channel_id,
                        "pollutant": t.pollutant,
                        "reason": reason,
                    }
                )
            else:
                targets.append(t)

        if args.max_targets is not None:
            targets = targets[: args.max_targets]

        print(f"Discovered profiles after explicit filters: {len(discovered)}")
        print(f"Excluded before preflight: {len(exclusions)}")
        print(f"Profiles entering preflight: {len(targets)}")

        write_json(output_dir / "excluded_profiles.json", exclusions)

        preflight_rows: list[dict[str, Any]] = []
        passed_targets: list[tuple[Target, dict[str, Any]]] = []

        for i, target in enumerate(targets, start=1):
            print(
                f"\nPREFLIGHT [{i}/{len(targets)}] "
                f"station={target.station_id} ({target.station_name}) "
                f"channel={target.channel_id} pollutant={target.pollutant}"
            )

            pf = await preflight_target(client, target, args)
            print(
                f"  result={pf['reason']} "
                f"passed_years={pf['passed_years']} "
                f"units={pf['observed_units']}"
            )

            row = {
                "station_id": target.station_id,
                "station_name": target.station_name,
                "channel_id": target.channel_id,
                "pollutant": target.pollutant,
                "passed": pf["passed"],
                "reason": pf["reason"],
                "passed_years": ",".join(map(str, pf["passed_years"])),
                "units": ",".join(pf["observed_units"]),
            }
            preflight_rows.append(row)

            if pf["passed"]:
                passed_targets.append((target, pf))

            write_json(output_dir / "preflight_summary.json", preflight_rows)

        write_csv(
            output_dir / "preflight_summary.csv",
            preflight_rows,
            [
                "station_id",
                "station_name",
                "channel_id",
                "pollutant",
                "passed",
                "reason",
                "passed_years",
                "units",
            ],
        )

        print("\n=== PREFLIGHT COMPLETE ===")
        print(f"tested={len(preflight_rows)}")
        print(f"passed={len(passed_targets)}")
        print(f"failed={len(preflight_rows)-len(passed_targets)}")

        if args.preflight_only:
            print("PRE-FLIGHT ONLY: no full historical profiles downloaded.")
            return

        full_summary: list[dict[str, Any]] = []
        started = time.time()

        for i, (target, pf) in enumerate(passed_targets, start=1):
            print(
                f"\nFULL BUILD [{i}/{len(passed_targets)}] "
                f"station={target.station_id} ({target.station_name}) "
                f"channel={target.channel_id} pollutant={target.pollutant}"
            )

            try:
                row = await build_full_profile(
                    client, target, pf, args, profiles_dir
                )
            except Exception as exc:
                row = {
                    "station_id": target.station_id,
                    "station_name": target.station_name,
                    "channel_id": target.channel_id,
                    "pollutant": target.pollutant,
                    "status": "error",
                    "preflight": "passed",
                    "skipped_existing": False,
                    "unit": None,
                    "ok_buckets": None,
                    "total_hourly_values": None,
                    "profile_file": None,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }

            full_summary.append(row)
            write_json(output_dir / "national_baseline_summary.json", full_summary)
            write_csv(
                output_dir / "national_baseline_summary.csv",
                full_summary,
                [
                    "station_id",
                    "station_name",
                    "channel_id",
                    "pollutant",
                    "status",
                    "preflight",
                    "skipped_existing",
                    "unit",
                    "ok_buckets",
                    "total_hourly_values",
                    "profile_file",
                    "error",
                ],
            )

        elapsed = time.time() - started
        counts = defaultdict(int)
        for row in full_summary:
            counts[row["status"]] += 1

        print("\n=== NATIONAL BASELINE V2 COMPLETE ===")
        print(f"full_profiles_processed={len(full_summary)}")
        print("status_counts=", dict(sorted(counts.items())))
        print(f"elapsed_seconds={round(elapsed, 2)}")
        print(f"output_dir={output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
