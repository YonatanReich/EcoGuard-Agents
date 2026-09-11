"""Hourly Open-Meteo conditions for every service-area cell.

The only thing in the system that calls Open-Meteo. The fire-risk model and
the per-coordinate API endpoints read what this writes, through
`ecoguard.database.repositories.weather_history`, rather than each holding
their own provider client.

What it fetches is decided by what the database is missing, not by a fixed
window. That one change does three jobs at once:

  * an outage of any length repairs itself, where a six-hour lookback could
    only ever repair an outage shorter than six hours
  * a freshly migrated database backfills to the depth the model needs instead
    of being useless for a week
  * a steady-state tick that finds nothing missing makes no provider calls at
    all, so running more often costs nothing
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from ecoguard.collection.base import BaseCollector, service_area_cells
from ecoguard.database.repositories.weather_history import (
    HISTORY_HOURS,
    contiguous_ranges,
    missing_hours,
)
from services.open_meteo_hourly_client import (
    HOURLY_VARIABLES,
    HourlyProviderError,
    OpenMeteoHourlyClient,
)

logger = logging.getLogger(__name__)

# How much one tick may ask the provider for, measured in cell-hours — cells
# multiplied by hours, which is what Open-Meteo actually charges for. Counting
# requests instead is the trap: one request carries a single hour or a hundred
# and sixty-eight, so a fixed request budget lets the volume swing by two
# orders of magnitude. A cold-start tick of 21 requests asked for 93,450
# cell-hours and was rate limited; a steady-state tick of 24 requests asks for
# 1,174 and is nothing.
#
# 25,000 sits above the largest tick observed to succeed and far above anything
# steady state produces, so only a backfill is ever chunked by it.
MAX_CELL_HOURS_PER_TICK = 25_000

# Secondary guard on wall-clock, not volume: at the client's 15-second pacing,
# 48 requests is about twelve minutes, comfortably inside the hourly interval.
MAX_REQUESTS_PER_TICK = 48


def _current_hour(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def records_from_batch(
    cells, responses: list[dict[str, Any]], *, before: datetime
) -> list[dict[str, Any]]:
    """Flatten one batched response into one observation per cell per hour.

    Hours at or after `before` are dropped even though the request asked for a
    closed past window: Open-Meteo serves forecast from the same endpoint, and
    a forecast stored as an observation would be indistinguishable from one
    later on. The guard is cheap and the failure it prevents is silent.
    """
    records = []
    for cell, response in zip(cells, responses):
        hourly = response["hourly"]
        for index, stamp in enumerate(hourly["time"]):
            observed_at = datetime.fromisoformat(stamp)
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            if observed_at >= before:
                continue
            records.append({
                "cell_id": cell.cell_id,
                "latitude": cell.latitude,
                "longitude": cell.longitude,
                "observed_at": observed_at,
                "payload": {
                    variable: hourly[variable][index] for variable in HOURLY_VARIABLES
                },
            })
    return records


def plan_fetches(
    gaps: dict[str, list[datetime]],
    *,
    batch_size: int,
    cell_hour_budget: int = MAX_CELL_HOURS_PER_TICK,
    request_budget: int = MAX_REQUESTS_PER_TICK,
) -> list[tuple[tuple[datetime, datetime], list[str]]]:
    """Turn per-cell missing hours into a bounded list of provider requests.

    Cells are grouped by their missing-hour signature first. In the normal case
    every cell is missing the same single hour, so the whole national grid
    collapses to one range and `ceil(cells / batch_size)` requests.

    Newest ranges are planned first, and the plan stops at whichever budget
    binds. What survives a truncated plan is the recent data every consumer
    actually reads; the older backfill waits for the next tick.
    """
    by_signature: dict[tuple[datetime, ...], list[str]] = defaultdict(list)
    for cell_id, hours in gaps.items():
        by_signature[tuple(sorted(hours))].append(cell_id)

    candidates: list[tuple[tuple[datetime, datetime], list[str]]] = []
    for signature, cell_ids in by_signature.items():
        ordered = sorted(cell_ids)
        for window in contiguous_ranges(signature):
            for start in range(0, len(ordered), batch_size):
                candidates.append((window, ordered[start:start + batch_size]))

    candidates.sort(key=lambda item: item[0][1], reverse=True)

    planned: list[tuple[tuple[datetime, datetime], list[str]]] = []
    spent = 0
    for window, cell_ids in candidates:
        hours = int((window[1] - window[0]).total_seconds() // 3600) + 1
        cost = hours * len(cell_ids)
        # Always allow the first request through. A single batch is at most
        # HISTORY_HOURS x batch_size, well under any sane budget, but a tick
        # that planned nothing would never make progress.
        if planned and (spent + cost > cell_hour_budget or len(planned) >= request_budget):
            break
        planned.append((window, cell_ids))
        spent += cost
    return planned


class WeatherCollector(BaseCollector):
    source = "weather"

    def __init__(
        self,
        client: OpenMeteoHourlyClient | None = None,
        *,
        history_hours: int = HISTORY_HOURS,
        max_cell_hours_per_tick: int = MAX_CELL_HOURS_PER_TICK,
        max_requests_per_tick: int = MAX_REQUESTS_PER_TICK,
    ):
        # One long-lived client for the process. The scheduler builds the
        # collector once at import, so the client's pacing clock and 429
        # cooldown persist across ticks — a fresh client per tick would forget
        # that it had just been rate limited.
        self.client = client or OpenMeteoHourlyClient()
        self.history_hours = history_hours
        self.max_cell_hours_per_tick = max_cell_hours_per_tick
        self.max_requests_per_tick = max_requests_per_tick

    def fetch(self) -> list[dict[str, Any]]:
        cells = service_area_cells()
        by_id = {cell.cell_id: cell for cell in cells}

        # The newest hour Open-Meteo has finished reporting. The current hour is
        # still forecast, so the window ends one hour back.
        current_hour = _current_hour(datetime.now(timezone.utc))
        last = current_hour - timedelta(hours=1)
        first = last - timedelta(hours=self.history_hours - 1)

        gaps = missing_hours(list(by_id), first, last)
        if not gaps:
            logger.info("weather collector: no gaps, nothing to fetch")
            return []

        planned = plan_fetches(
            gaps,
            batch_size=self.client.batch_size,
            cell_hour_budget=self.max_cell_hours_per_tick,
            request_budget=self.max_requests_per_tick,
        )
        outstanding = sum(len(hours) for hours in gaps.values())
        logger.info(
            "weather collector: %s cells missing %s cell-hours, %s requests planned",
            len(gaps), outstanding, len(planned),
        )

        records: list[dict[str, Any]] = []
        for index, ((window_start, window_end), cell_ids) in enumerate(planned):
            batch = [by_id[cell_id] for cell_id in cell_ids]
            try:
                responses = self.client.fetch_range(
                    [(cell.latitude, cell.longitude) for cell in batch],
                    window_start,
                    window_end,
                )
            except HourlyProviderError as error:
                # Keep what the earlier batches already returned. Letting this
                # propagate discarded the whole tick — a run that was rate
                # limited on its ninth request threw away the eight that had
                # succeeded, then asked for exactly the same data next tick and
                # was rate limited again. Storing the partial result is what
                # breaks that loop: the gap query sees less missing every time.
                #
                # Nothing at all is still a failure, so the run is recorded as
                # one and the reason survives in collector_runs.
                if not records:
                    raise
                logger.warning(
                    "weather collector: stopping early after %s — keeping %s records, %s of %s requests unspent",
                    error.category, len(records), len(planned) - index, len(planned),
                )
                break
            records.extend(records_from_batch(batch, responses, before=current_hour))
        return records
