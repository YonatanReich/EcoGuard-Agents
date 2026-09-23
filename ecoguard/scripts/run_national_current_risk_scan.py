"""Run one offline national Current Risk snapshot from existing local caches."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from ecoguard.analyzers.fire.national_scan import DEFAULT_OUTPUT_PATH, NationalCurrentRiskScanService


def main() -> int:
    """Run one national risk snapshot from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-time", type=datetime.fromisoformat)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    result = NationalCurrentRiskScanService().scan_and_save(args.evaluation_time, args.output)
    print(json.dumps(result["summary"], indent=2))
    return 0 if result["status"] in {"success", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
