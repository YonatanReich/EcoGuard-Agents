#!/usr/bin/env python
"""Build compact five-minute baseline profiles from the immutable local cache."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ecoguard.detectors.air_pollution.five_minute_baseline import (  # noqa: E402
    BASELINE_FAMILY,
    build_profile,
    discover_cache_profiles,
)
from ecoguard.detectors.air_pollution.five_minute_baseline_validation import (  # noqa: E402
    validate_artifacts,
)

DEFAULT_CACHE = REPO_ROOT / "venv/phase2-output/air-pollution-five-minute-cache"
DEFAULT_OUTPUT = REPO_ROOT / "venv/phase2-output/five-minute-observation-baseline-v1"


def _json_bytes(payload) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _profile_filename(profile) -> str:
    identity = profile["identity"]
    pollutant = identity["pollutant"].lower().replace(".", "_")
    return f"station_{identity['station_id']}_channel_{identity['channel_id']}_{pollutant}_2021_2025.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-profiles", type=int, default=388)
    parser.add_argument("--max-profiles", type=int)
    parser.add_argument("--skip-cache-checksums", action="store_true",
                        help="Skip only the final cache re-hash; building always hashes each source file")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    groups = discover_cache_profiles(args.cache_dir)
    if len(groups) != args.expected_profiles:
        raise SystemExit(f"expected {args.expected_profiles} cache identities; found {len(groups)}")
    selected = groups[:args.max_profiles] if args.max_profiles is not None else groups
    profiles_dir = args.output_dir / "profiles"
    status_counts = {"FULL_BASELINE": 0, "PARTIAL_BASELINE": 0, "INSUFFICIENT_HISTORY": 0}
    usable = insufficient = 0
    for index, files in enumerate(selected, start=1):
        profile = build_profile(files)
        destination = profiles_dir / _profile_filename(profile)
        content = _json_bytes(profile)
        if destination.exists() and destination.read_bytes() != content:
            raise SystemExit(f"refusing to overwrite changed artifact: {destination}")
        if not destination.exists():
            _write_atomic(destination, content)
        status_counts[profile["coverage_status"]] += 1
        usable += profile["coverage_summary"]["usable_buckets"]
        insufficient += profile["coverage_summary"]["insufficient_buckets"]
        print(
            f"profiles {index} / {len(selected)} "
            f"station={profile['identity']['station_id']} "
            f"channel={profile['identity']['channel_id']} pollutant={profile['identity']['pollutant']}"
        )

    expected_output = len(selected)
    validation = validate_artifacts(
        profiles_dir,
        cache_dir=None if args.skip_cache_checksums else args.cache_dir,
        expected_profiles=expected_output,
    )
    summary = {
        "baseline_family": BASELINE_FAMILY,
        "profile_count": expected_output,
        "bucket_count": expected_output * 288,
        "usable_buckets": usable,
        "insufficient_buckets": insufficient,
        "status_counts": status_counts,
        "validation": validation["validation"],
        "validation_errors": validation["errors"],
        "cache_checksums_verified": validation["cache_checksums_verified"],
    }
    _write_atomic(args.output_dir / "build_summary.json", _json_bytes(summary))
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    print(f"runtime_seconds={time.perf_counter() - started:.3f}")
    return 0 if validation["validation"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
