"""Convert newly persisted hydrometric readings to shared flood signals."""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from ecoguard.database.repositories.collector_runs import (
    last_success_at,
    log_finish,
    log_start,
)
from ecoguard.database.repositories.flood_detection import (
    load_stream_ids,
    load_window,
)
from ecoguard.database.repositories.observations import read_observations_batch
from ecoguard.detectors.flood.detection_agent import FloodDetectionAgent
from ecoguard.detectors.flood.station_rules import HYDROMETRIC_SOURCE
from ecoguard.shared.signals import CellSignal
from ecoguard.detectors.shared.window import catchup_floor


RUN_SOURCE = "flood_detection"
DETECTION_BATCH_SIZE = 1000

# How far back to read arrivals when resuming after a gap. Three hours is the
# flood quiet period, so anything older belongs to an episode the coordinator
# would already have closed. The consecutive-reading history a judgement needs
# is loaded separately and is unaffected by this.
CATCHUP = timedelta(hours=3)
logger = logging.getLogger(__name__)


def _source_station_ids(observations: list[dict[str, Any]]) -> list[int]:
    """The gauge ids present in these readings."""
    return sorted(
        {
            int(station["source_station_id"])
            for observation in observations
            for station in (observation.get("payload") or {}).get("stations", [])
            if station.get("source_station_id") is not None
        }
    )


@live_actor("detector.flood")
def detect_new(
    *,
    agent: FloodDetectionAgent | None = None,
    at: datetime | None = None,
) -> list[CellSignal]:
    """Evaluate every newly ingested eligible gauge row exactly as a batch.

    Like the other scheduled detectors, the last successful detector run is
    the ingestion bookmark. The hydrometric history window is loaded only to
    confirm that each new reading has a consecutive predecessor.
    """
    selected_agent = agent or FloodDetectionAgent()
    through = at or datetime.now(timezone.utc)
    if through.tzinfo is None or through.utcoffset() is None:
        raise ValueError("at must carry a UTC offset")
    through = through.astimezone(timezone.utc)
    since = catchup_floor(last_success_at(RUN_SOURCE), through, limit=CATCHUP)
    run_id = log_start(RUN_SOURCE)

    try:
        cursor_at = since
        cursor_id = 0 if since is not None else None
        pending: list[dict[str, Any]] = []

        while True:
            rows = read_observations_batch(
                HYDROMETRIC_SOURCE,
                ingested_after=cursor_at,
                after_id=cursor_id,
                ingested_through=through,
                limit=DETECTION_BATCH_SIZE,
            )
            if not rows:
                break
            pending.extend(rows)
            tail = rows[-1]
            next_cursor = (tail["ingested_at"], int(tail["id"]))
            if cursor_at is not None and next_cursor <= (cursor_at, cursor_id or 0):
                raise RuntimeError("persisted ingestion cursor did not advance")
            cursor_at, cursor_id = next_cursor
            if len(rows) < DETECTION_BATCH_SIZE:
                break

        fresh = [row for row in pending if selected_agent.accepts_pending(row)]
        if not fresh:
            result: list[CellSignal] = []
        else:
            by_cell_targets: dict[str, set[datetime]] = defaultdict(set)
            for row in fresh:
                by_cell_targets[str(row["cell_id"])].add(row["observed_at"])

            earliest = min(row["observed_at"] for row in fresh)
            latest = max(row["observed_at"] for row in fresh)
            window = load_window(
                sorted(by_cell_targets),
                HYDROMETRIC_SOURCE,
                observed_since=earliest - selected_agent.lookback,
                observed_through=latest,
            )
            stream_ids = load_stream_ids(_source_station_ids(window))
            by_cell_window: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in window:
                by_cell_window[str(row["cell_id"])].append(row)

            signals = []
            for cell_id in sorted(by_cell_targets):
                evaluation = selected_agent.evaluate(
                    cell_id=cell_id,
                    observations=by_cell_window.get(cell_id, []),
                    stream_ids=stream_ids,
                    target_observed_at=by_cell_targets[cell_id],
                )
                signals.extend(evaluation)
            result = sorted(signals, key=lambda item: item.observed_at)

        log_finish(
            run_id,
            status="ok",
            rows_written=len(result),
        )
        logger.info(
            "flood: %s signals from %s persisted rows",
            len(result),
            len(pending),
        )
        return result
    except Exception as error:
        log_finish(
            run_id,
            status="failed",
            error=f"{type(error).__name__}: {error}",
        )
        raise
