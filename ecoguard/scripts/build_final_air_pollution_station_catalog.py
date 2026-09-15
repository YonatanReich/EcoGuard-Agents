#!/usr/bin/env python3
"""
EcoGuard - Final Air Pollution Station Catalog

Builds one station-level catalog for:
NO2, O3, PM10, PM2.5, SO2

For each station/pollutant it distinguishes:
- FULL_BASELINE
- PARTIAL_BASELINE
- INSUFFICIENT_HISTORY
- EXCLUDED_MOBILE_OR_INACTIVE
- NOT_MEASURED

It combines:
1) current official Ministry/Envista station metadata
2) baseline profile JSON files already built under national-baseline-v2/profiles

No historical downloads. No DB writes.
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE2_DEPS = REPO_ROOT / "venv" / "phase2-deps"
if PHASE2_DEPS.exists():
    sys.path.insert(0, str(PHASE2_DEPS))

import aiohttp  # noqa: E402
from air_sviva_api.client import SvivaAirClient  # noqa: E402

POLLUTANTS = ["NO2", "O3", "PM10", "PM2.5", "SO2"]
MOBILE_MARKERS = ("ניידת", "קרון")


def norm_pol(name: Any) -> str:
    p = str(name or "").upper().replace(" ", "")
    if p in {"PM25", "PM2_5"}:
        return "PM2.5"
    return p


def exclusion_reason(station_name: str, active: Any) -> str | None:
    if active is False:
        return "inactive_monitor"
    if "לא פעילה" in station_name or "לא פעיל" in station_name:
        return "station_name_marks_inactive"
    for marker in MOBILE_MARKERS:
        if marker in station_name:
            return f"mobile_or_temporary_name:{marker}"
    return None


def load_profiles(profiles_dir: Path):
    profiles = defaultdict(list)
    for path in profiles_dir.glob("*.json"):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        sid = d.get("station", {}).get("id")
        pol = norm_pol(d.get("pollutant"))
        if sid is None or pol not in POLLUTANTS:
            continue
        profiles[(int(sid), pol)].append(d)
    return profiles


def best_profile(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def rank(d):
        ok = int(d.get("coverage_summary", {}).get("ok_buckets", 0) or 0)
        status = d.get("profile_status")
        status_rank = {"ok": 3, "partial_coverage": 2, "insufficient_history": 1}.get(status, 0)
        return (status_rank, ok)

    return max(rows, key=rank)


async def main():
    profiles_dir = REPO_ROOT / "venv" / "phase2-output" / "national-baseline-v2" / "profiles"
    output_dir = REPO_ROOT / "venv" / "phase2-output" / "national-baseline-v2"
    output_dir.mkdir(parents=True, exist_ok=True)

    built = load_profiles(profiles_dir)

    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        client = SvivaAirClient(session)
        await client.generate_token()
        regions = await client.get_regions()

    stations = {}
    monitors = defaultdict(list)

    for region in regions:
        for st in (getattr(region, "stations", None) or []):
            sid = getattr(st, "station_id", None)
            if sid is None:
                continue
            sid = int(sid)
            name = str(getattr(st, "name", None) or f"station_{sid}")
            stations[sid] = name

            for mon in (getattr(st, "monitors", None) or []):
                pol = norm_pol(getattr(mon, "name", ""))
                if pol not in POLLUTANTS:
                    continue
                cid = getattr(mon, "channel_id", None)
                if cid is None:
                    continue
                monitors[(sid, pol)].append(
                    {
                        "channel_id": int(cid),
                        "active": getattr(mon, "active", None),
                        "metadata_unit": getattr(mon, "units", None),
                    }
                )

    long_rows = []
    wide_rows = []

    for sid in sorted(stations):
        sname = stations[sid]
        wide = {"station_id": sid, "station_name": sname}

        for pol in POLLUTANTS:
            mons = monitors.get((sid, pol), [])
            profs = built.get((sid, pol), [])
            best = best_profile(profs)

            if best:
                ok_buckets = int(best.get("coverage_summary", {}).get("ok_buckets", 0) or 0)
                pstatus = best.get("profile_status")
                status = "FULL_BASELINE" if pstatus == "ok" else "PARTIAL_BASELINE"
                channels = sorted(
                    {
                        int(d.get("channel_id"))
                        for d in profs
                        if d.get("channel_id") is not None
                    }
                )
                unit = best.get("historical_unit")
                reason = ""
            elif not mons:
                status = "NOT_MEASURED"
                ok_buckets = 0
                channels = []
                unit = ""
                reason = ""
            else:
                reasons = [exclusion_reason(sname, m.get("active")) for m in mons]
                nonexcluded = [r for r in reasons if r is None]

                if nonexcluded:
                    status = "INSUFFICIENT_HISTORY"
                    reason = "measured_but_no_qualified_multiyear_baseline"
                else:
                    status = "EXCLUDED_MOBILE_OR_INACTIVE"
                    reason = ";".join(sorted({r for r in reasons if r}))

                ok_buckets = 0
                channels = sorted({m["channel_id"] for m in mons})
                unit = ",".join(sorted({str(m["metadata_unit"]) for m in mons if m.get("metadata_unit")}))

            coverage_pct = round(ok_buckets / 288 * 100, 1) if ok_buckets else 0.0

            long_rows.append(
                {
                    "station_id": sid,
                    "station_name": sname,
                    "pollutant": pol,
                    "status": status,
                    "channels": ",".join(map(str, channels)),
                    "ok_buckets": ok_buckets,
                    "coverage_pct": coverage_pct,
                    "unit": unit,
                    "reason": reason,
                }
            )

            wide[f"{pol}_status"] = status
            wide[f"{pol}_coverage"] = f"{ok_buckets}/288" if status in {"FULL_BASELINE", "PARTIAL_BASELINE"} else "-"
            wide[f"{pol}_channels"] = ",".join(map(str, channels)) if channels else "-"

        wide_rows.append(wide)

    long_path = output_dir / "station_baseline_catalog_final_long.csv"
    wide_path = output_dir / "station_baseline_catalog_final_wide.csv"
    summary_path = output_dir / "station_baseline_catalog_final_summary.json"

    long_cols = [
        "station_id", "station_name", "pollutant", "status",
        "channels", "ok_buckets", "coverage_pct", "unit", "reason"
    ]
    with long_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=long_cols)
        w.writeheader()
        w.writerows(long_rows)

    wide_cols = ["station_id", "station_name"]
    for pol in POLLUTANTS:
        wide_cols += [f"{pol}_status", f"{pol}_coverage", f"{pol}_channels"]

    with wide_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=wide_cols)
        w.writeheader()
        w.writerows(wide_rows)

    status_counts = defaultdict(int)
    pollutant_counts = {p: defaultdict(int) for p in POLLUTANTS}

    for r in long_rows:
        status_counts[r["status"]] += 1
        pollutant_counts[r["pollutant"]][r["status"]] += 1

    stations_with_any_baseline = {
        r["station_id"]
        for r in long_rows
        if r["status"] in {"FULL_BASELINE", "PARTIAL_BASELINE"}
    }

    summary = {
        "unique_stations_in_official_metadata": len(stations),
        "stations_with_at_least_one_baseline": len(stations_with_any_baseline),
        "baseline_profile_files_found": sum(len(v) for v in built.values()),
        "status_counts_all_station_pollutant_pairs": dict(status_counts),
        "by_pollutant": {p: dict(v) for p, v in pollutant_counts.items()},
        "wide_catalog": str(wide_path),
        "long_catalog": str(long_path),
    }

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== FINAL STATION CATALOG COMPLETE ===")
    print("unique_stations_in_official_metadata =", len(stations))
    print("stations_with_at_least_one_baseline =", len(stations_with_any_baseline))
    print("baseline_profile_files_found =", sum(len(v) for v in built.values()))
    print("\nBY POLLUTANT")
    for pol in POLLUTANTS:
        print(pol, dict(pollutant_counts[pol]))
    print("\nWIDE =", wide_path)
    print("LONG =", long_path)
    print("SUMMARY =", summary_path)


if __name__ == "__main__":
    asyncio.run(main())
