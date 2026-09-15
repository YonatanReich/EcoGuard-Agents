#!/usr/bin/env python
"""Audit or explicitly activate the five-minute Air Pollution baseline cohort."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ecoguard.detectors.air_pollution.baseline_activation import (  # noqa: E402
    EXPECTED_TARGET_PROFILES,
    TARGET_BASELINE_FAMILY,
    BaselineActivationError,
)


def audit(family: str):
    from ecoguard.database.repositories.air_pollution_baseline_activation import (
        audit_baseline_family_activation,
    )
    return audit_baseline_family_activation(
        family=family, expected_profile_count=EXPECTED_TARGET_PROFILES,
    )


def activate(family: str):
    from ecoguard.database.repositories.air_pollution_baseline_activation import (
        activate_baseline_family,
    )
    return activate_baseline_family(
        family=family, expected_profile_count=EXPECTED_TARGET_PROFILES,
    )


def readiness_summary(report):
    return {
        "family": report["family"],
        "ready": report["ready"],
        "errors": report["errors"],
        "counts": report["counts"],
        "projected_after": report["projected_after"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--family", required=True, choices=[TARGET_BASELINE_FAMILY],
        help="Required explicit target; no other family is accepted.",
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args(argv)
    if args.confirm_write and not args.write:
        parser.error("--confirm-write requires --write")
    if args.write and not args.confirm_write:
        parser.error("activation requires both --write and --confirm-write")

    try:
        readiness = audit(args.family)
        output = {
            "mode": "WRITE" if args.write else "DRY_RUN",
            "family": args.family,
            "database_modified": False,
            "readiness": readiness_summary(readiness),
        }
        if not readiness["ready"]:
            print(json.dumps(output, indent=2, default=str))
            return 1
        if args.write:
            # The write entry point repeats the complete validation under row
            # locks; this earlier dry-run is informational, not the write gate.
            activation = activate(args.family)
            output["activation"] = {
                "family": activation["family"],
                "before": activation["before"],
                "after": activation["after"],
                "activated_count": activation["activated_count"],
                "superseded_count": activation["superseded_count"],
                "final_active_count": activation["final_active_count"],
            }
            output["database_modified"] = True
        print(json.dumps(output, indent=2, default=str))
        return 0
    except BaselineActivationError as error:
        print(json.dumps({
            "mode": "WRITE" if args.write else "DRY_RUN",
            "family": args.family,
            "database_modified": False,
            "error": str(error),
        }, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
