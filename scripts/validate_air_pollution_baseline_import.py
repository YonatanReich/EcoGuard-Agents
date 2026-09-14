"""Offline validation and stdout-only manifest; never imports database/client code."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.air_pollution_baseline_import_validation import build_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "venv/phase2-output/national-baseline-v2")
    parser.add_argument("--summary", action="store_true", help="Omit per-profile checksums/catalog/details from stdout")
    args = parser.parse_args()
    manifest = build_manifest(args.source / "profiles", args.source / "station_baseline_catalog_final_long.csv")
    if args.summary:
        negatives = manifest.pop("negative_profiles")
        summary = {}
        for p in negatives:
            pol = p["identity"][2]
            item = summary.setdefault(pol, {"stations": [], "profiles": 0, "negative_fields": 0, "min": 0, "max": None, "fields": {}, "profiles_by_field": {}, "minimum_location": None})
            item["stations"].append(p["identity"][0])
            item["profiles"] += 1
            for field, rows in p["fields"].items():
                values = [r["value"] for r in rows]
                item["negative_fields"] += len(values)
                if min(values) < item["min"]:
                    item["min"] = min(values)
                    item["minimum_location"] = {"identity": p["identity"], "field": field,
                                                **min(rows, key=lambda r: r["value"])}
                item["max"] = max(values) if item["max"] is None else max(item["max"], max(values))
                item["fields"][field] = item["fields"].get(field, 0) + len(values)
                item["profiles_by_field"][field] = item["profiles_by_field"].get(field, 0) + 1
        for item in summary.values():
            item["stations"] = sorted(set(item["stations"]))
        manifest["negative_summary"] = summary
        manifest["negative_profile_count"] = len(negatives)
        manifest.pop("versions")
        manifest.pop("station_catalog")
    print(json.dumps(manifest, ensure_ascii=True, indent=2, allow_nan=False))
    return 1 if manifest["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
