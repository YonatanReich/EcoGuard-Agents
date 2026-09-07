"""Hourly Open-Meteo conditions for every service-area cell."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ecoguard.collection.base import BaseCollector, service_area_cells
from services.open_meteo_hourly_client import HOURLY_VARIABLES, OpenMeteoHourlyClient

# How far back each tick re-reads. Long enough that a run of failed ticks
# backfills itself, short enough that the ~1,200 rows an hour costs are not
# re-sent twenty-four times a day.
# ponytail: fixed window, not a per-cell high-water mark. Query the stored
# max(observed_at) per cell if the redundant inserts ever show up in the bill.
LOOKBACK_HOURS = 6


def _current_hour(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def records_from_batch(
    cells, responses: list[dict[str, Any]], *, before: datetime, since: datetime | None = None
) -> list[dict[str, Any]]:
    """Flatten one batched response into one observation per cell per hour.

    Hours at or after `before` are dropped: Open-Meteo returns the rest of the
    day as forecast, and a forecast is not an observation. Hours before `since`
    are dropped as already stored.
    """
    records = []
    for cell, response in zip(cells, responses):
        hourly = response["hourly"]
        for index, stamp in enumerate(hourly["time"]):
            observed_at = datetime.fromisoformat(stamp)
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            if observed_at >= before or (since is not None and observed_at < since):
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


class WeatherCollector(BaseCollector):
    source = "weather"

    def __init__(self, client: OpenMeteoHourlyClient | None = None):
        # The repository's existing hourly client, not WeatherDataAgent: it
        # batches fifty coordinates per request and paces itself against
        # Open-Meteo's rate limit. One request per cell would be ~1,200 calls a
        # tick, roughly 57,000 a day, well past the free tier's 10,000.
        self.client = client or OpenMeteoHourlyClient()

    def fetch(self) -> list[dict[str, Any]]:
        """The last few complete hours, for every cell.

        Re-reading a window rather than only the newest hour is what makes a
        failed tick harmless: the next one backfills the hours it missed, and
        the unique constraint drops the ones already stored.
        """
        cells = service_area_cells()
        now = datetime.now(timezone.utc)
        current_hour = _current_hour(now)
        window_start = current_hour - timedelta(hours=LOOKBACK_HOURS)
        size = self.client.batch_size

        records = []
        for start in range(0, len(cells), size):
            batch = cells[start:start + size]
            responses = self.client.fetch_range(
                [(cell.latitude, cell.longitude) for cell in batch], window_start, now
            )
            records.extend(records_from_batch(
                batch, responses, before=current_hour, since=window_start
            ))
        return records
