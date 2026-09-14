"""Read persisted Air Pollution observations through active baseline detection."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from time import perf_counter

from services.air_pollution_observation_processing import (
    AirPollutionObservationProcessor,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since-minutes", type=int, default=240,
        help="Read rows ingested after this many minutes ago (default: 240).",
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--show", type=int, default=10,
        help="Maximum ordered result summaries to print (default: 10).",
    )
    args = parser.parse_args()
    if args.since_minutes < 1:
        parser.error("--since-minutes must be positive")
    if not 1 <= args.limit <= 5000:
        parser.error("--limit must be between 1 and 5000")
    if not 0 <= args.show <= args.limit:
        parser.error("--show must be between zero and --limit")

    started = perf_counter()
    boundary = datetime.now(timezone.utc) - timedelta(minutes=args.since_minutes)
    results = AirPollutionObservationProcessor().read_and_process(
        ingested_after=boundary,
        limit=args.limit,
    )
    print(json.dumps({
        "mode": "operational_active_read_only",
        "source": "air_pollution",
        "baseline_family": "five_minute_observation",
        "ingested_after": boundary.isoformat(),
        "row_count": len(results),
        "detector_statuses": dict(Counter(item.detector_status for item in results)),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "results": [
            {
                "observation_id": item.observation_id,
                "cell_id": item.cell_id,
                "ingested_at": item.ingested_at.isoformat() if item.ingested_at else None,
                "station_id": (
                    item.live_observation.provider_station_id
                    if item.live_observation else None
                ),
                "channel_id": (
                    item.live_observation.provider_channel_id
                    if item.live_observation else None
                ),
                "pollutant": item.live_observation.pollutant if item.live_observation else None,
                "unit": item.live_observation.measurement_unit if item.live_observation else None,
                "observed_at": (
                    item.live_observation.observed_at.isoformat()
                    if item.live_observation else None
                ),
                "live_value": item.live_value,
                "baseline_status": item.baseline_context.status,
                "baseline_p95": item.baseline_p95,
                "detector_status": item.detector_status,
                "detector_reason": item.detector_reason,
            }
            for item in results[:args.show]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
