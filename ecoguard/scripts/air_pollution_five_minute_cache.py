"""Downloading the five-minute air-quality history, once, onto disk.

Kept as month files so an interrupted download resumes rather than restarting,
and so the baseline builder can read one month at a time instead of holding
years in memory."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import aiohttp
from sqlalchemy import text

from ecoguard.database.engine import engine
from ecoguard.scripts.air_pollution_baseline_national_v2 import (
    SvivaAirClient,
    discover_targets,
    exclusion_reason,
    fetch_month,
    normalize_pollutant,
)

DEFAULT_CACHE_DIR = (
    REPO_ROOT / "venv" / "phase2-output" / "air-pollution-five-minute-cache"
)


def _as_dict(obj: Any) -> dict[str, Any]:
    """A value as a plain dictionary, whatever shape it arrived in."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, dict):
        return obj
    return vars(obj)


def _safe_slug(value: str) -> str:
    """A name safe to use as a filename."""
    out = []
    for ch in str(value):
        out.append(ch.lower() if ch.isalnum() else "_")
    return "_".join(filter(None, "".join(out).split("_"))) or "unknown"


def load_profile_identities() -> list[dict[str, str]]:
    """
    Read the exact completed_hour identities already persisted by EcoGuard.

    The transaction is explicitly READ ONLY and is rolled back after the SELECT.
    """
    sql = text(
        """
        SELECT provider, station_id, channel_id, pollutant, canonical_unit
        FROM air_pollution_baseline_profiles
        WHERE baseline_family = 'completed_hour'
        ORDER BY provider, station_id, channel_id, pollutant, canonical_unit
        """
    )

    with engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            rows = [dict(r) for r in conn.execute(sql).mappings().all()]
        finally:
            tx.rollback()

    return [
        {
            "provider": str(r["provider"]),
            "station_id": str(r["station_id"]),
            "channel_id": str(r["channel_id"]),
            "pollutant": normalize_pollutant(r["pollutant"]),
            "canonical_unit": str(r["canonical_unit"]),
        }
        for r in rows
    ]


def target_key(target: Any) -> tuple[str, str, str]:
    """What makes one station-and-pollutant series distinct."""
    return (
        str(target.station_id),
        str(target.channel_id),
        normalize_pollutant(target.pollutant),
    )


def cache_file(
    cache_dir: Path,
    target: Any,
    year: int,
    month: int,
) -> Path:
    """Where one month of one series is kept."""
    station = _safe_slug(str(target.station_id))
    channel = _safe_slug(str(target.channel_id))
    pollutant = _safe_slug(normalize_pollutant(target.pollutant))
    return (
        cache_dir
        / f"station_{station}"
        / f"channel_{channel}_{pollutant}"
        / f"{year:04d}-{month:02d}.json.gz"
    )


def cache_is_complete(path: Path) -> bool:
    """Whether a cached month was fully downloaded."""
    if not path.exists():
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("complete") is True and isinstance(payload.get("points"), list)
    except Exception:
        return False


def write_cache_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write a cache file in one step, so a crash cannot leave it half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), default=str)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def normalize_points(response: Any) -> list[dict[str, Any]]:
    """
    Preserve the provider's returned point payloads as faithfully as possible.
    No valid/sentinel/unit/off-grid filtering is done here.
    """
    return [_as_dict(point) for point in (getattr(response, "data", None) or [])]


async def main() -> None:
    """Download the history cache from the command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--station-id", type=str, default=None)
    parser.add_argument("--pollutant", type=str, default=None)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff", type=float, default=1.0)
    parser.add_argument("--request-delay", type=float, default=0.05)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args()

    if args.end_year < args.start_year:
        raise SystemExit("--end-year must be >= --start-year")

    identities = load_profile_identities()
    expected_keys = {
        (r["station_id"], r["channel_id"], r["pollutant"]) for r in identities
    }
    print(f"DB completed_hour identities: {len(identities)}")

    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        client = SvivaAirClient(session)
        await client.generate_token()

        discovered = await discover_targets(client)
        matching = []
        discovered_by_key = {}

        for target in discovered:
            # Reuse the same production filtering rules as national-v2.
            # Mobile/inactive targets are not allowed for the existing persisted profile set.
            reason = exclusion_reason(target, False, False)
            if reason:
                continue
            discovered_by_key[target_key(target)] = target

        missing = sorted(expected_keys - set(discovered_by_key))
        if missing:
            print(f"WARNING: {len(missing)} persisted identities were not discovered live.")
            for key in missing[:20]:
                print(f"  missing target: {key}")
            if len(missing) > 20:
                print(f"  ... and {len(missing) - 20} more")

        for key in sorted(expected_keys):
            target = discovered_by_key.get(key)
            if target is not None:
                matching.append(target)

        if args.station_id is not None:
            matching = [t for t in matching if str(t.station_id) == args.station_id]

        if args.pollutant is not None:
            wanted = normalize_pollutant(args.pollutant)
            matching = [t for t in matching if normalize_pollutant(t.pollutant) == wanted]

        if args.max_targets is not None:
            matching = matching[: args.max_targets]

        print(f"Targets to cache: {len(matching)}")
        print(f"Cache dir: {args.cache_dir}")

        completed = 0
        skipped = 0
        failed = 0
        total_months = len(matching) * (args.end_year - args.start_year + 1) * 12

        for target_index, target in enumerate(matching, start=1):
            print(
                f"\n[{target_index}/{len(matching)}] "
                f"station={target.station_id} channel={target.channel_id} "
                f"pollutant={target.pollutant}"
            )

            for year in range(args.start_year, args.end_year + 1):
                for month in range(1, 13):
                    out = cache_file(args.cache_dir, target, year, month)

                    if not args.force and cache_is_complete(out):
                        skipped += 1
                        print(
                            f"  {year}-{month:02d} CACHED "
                            f"progress={completed + skipped + failed}/{total_months}"
                        )
                        continue

                    try:
                        response = await fetch_month(client, target, year, month, args)
                        points = normalize_points(response)
                        payload = {
                            "schema_version": "ecoguard-air-pollution-five-minute-cache-v1",
                            "complete": True,
                            "source": "Israel Ministry of Environmental Protection / Envista",
                            "station_id": str(target.station_id),
                            "station_name": str(target.station_name),
                            "channel_id": str(target.channel_id),
                            "pollutant": normalize_pollutant(target.pollutant),
                            "year": year,
                            "month": month,
                            "request_semantics": {
                                "resolution": "provider five-minute averages",
                                "timeBeginning": False,
                                "quality_filter_applied": False,
                                "unit_filter_applied": False,
                                "off_grid_filter_applied": False,
                            },
                            "point_count": len(points),
                            "points": points,
                        }
                        write_cache_atomic(out, payload)
                        completed += 1
                        print(
                            f"  {year}-{month:02d} SAVED points={len(points)} "
                            f"progress={completed + skipped + failed}/{total_months}"
                        )
                    except Exception as exc:
                        failed += 1
                        print(
                            f"  {year}-{month:02d} ERROR "
                            f"{type(exc).__name__}: {str(exc)[:200]}"
                        )

                    if args.request_delay > 0:
                        await asyncio.sleep(args.request_delay)

    print("\nDONE")
    print(f"new_months={completed}")
    print(f"cached_months={skipped}")
    print(f"failed_months={failed}")
    print(f"cache_dir={args.cache_dir}")
    if failed:
        print("Rerun the same command to retry only missing/failed months.")


if __name__ == "__main__":
    asyncio.run(main())
