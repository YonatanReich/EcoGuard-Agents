"""Validate and plan a compact baseline import. DRY-RUN is the default."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ecoguard.detectors.air_pollution.baseline_import import build_import_plan


def main(argv=None) -> int:
    """Import the baselines, reporting what would change unless told to apply it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=REPO_ROOT / "venv/phase2-output/national-baseline-v2")
    parser.add_argument("--write", action="store_true", help="Persist draft rows (never the default)")
    parser.add_argument("--confirm-write", action="store_true",
                        help="Second explicit guard required together with --write")
    parser.add_argument("--summary", action="store_true", help="Omit individual checksums")
    args = parser.parse_args(argv)
    if args.confirm_write and not args.write:
        parser.error("--confirm-write requires --write")
    if args.write and not args.confirm_write:
        parser.error("database writes require both --write and --confirm-write")

    plan = build_import_plan(args.source)
    output = {
        "mode": "WRITE" if args.write else "DRY_RUN",
        "database_imported": False,
        "row_counts": plan["row_counts"],
        "profile_status_counts": plan["profile_status_counts"],
        "bucket_counts": plan["bucket_counts"],
        "catalog_content_sha256": plan["catalog_content_sha256"],
        "imported_at": None,
        "imported_at_policy": plan["imported_at_policy"],
        "generated_at_null_count": sum(v["generated_at"] is None for v in plan["versions"]),
    }
    if not args.summary:
        output["profile_checksums"] = plan["profile_checksums"]
    if args.write:
        # Lazy import is intentional: default dry-run neither imports engine.py
        # nor reads DATABASE_URL, and therefore cannot connect accidentally.
        from ecoguard.database.repositories.air_pollution_baselines import import_baseline_plan
        output["write_result"] = import_baseline_plan(
            plan, progress=lambda message: print(message, file=sys.stderr, flush=True)
        )
        output["database_imported"] = True
    print(json.dumps(output, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
