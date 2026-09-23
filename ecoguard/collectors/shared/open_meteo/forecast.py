"""Weather forecasts, for fire-weather and flood lead time.

Writes far more rows per run than the observation collector - two days of lead
time for every cell it samples - which is why it samples a coarser grid and
runs only a few times a day."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ecoguard.collectors.base import BaseCollector, service_area_cells
from ecoguard.collectors.shared.open_meteo.client import (
    HourlyProviderError,
    OpenMeteoHourlyClient,
)

logger = logging.getLogger(__name__)

# Two days of hourly lead time. Long enough to cover "is tomorrow afternoon
# worse than now", short enough that every stored hour is still a forecast
# anyone would act on.
FORECAST_HORIZON_HOURS = 48

# Take every third cell in each direction, so about one in nine — roughly a
# 15 km spacing. See the module docstring: this is below the provider model's
# own resolution, so it costs nothing real.
FORECAST_CELL_STRIDE = 3

# Same per-tick ceiling the observation collector uses, in cell-hours, because
# it is the same provider and the same weighting.
MAX_CELL_HOURS_PER_TICK = 25_000


def forecast_cells(stride: int = FORECAST_CELL_STRIDE):
    """Every stride-th service-area cell, in both directions.

    Striding on the grid's own row and column rather than on position in the
    list: the list is row-major and rows differ in length, so taking every
    ninth element would walk diagonally across the country and leave bands with
    no forecast at all.
    """
    return tuple(
        cell
        for cell in service_area_cells()
        if cell.grid_row % stride == 0 and cell.grid_col % stride == 0
    )


class WeatherForecastCollector(BaseCollector):
    source = "weather_forecast"

    def __init__(
        self,
        client: OpenMeteoHourlyClient | None = None,
        *,
        horizon_hours: int = FORECAST_HORIZON_HOURS,
        stride: int = FORECAST_CELL_STRIDE,
    ):
        """Build the collector. Client and clock are injectable for testing."""
        self.client = client or OpenMeteoHourlyClient()
        self.horizon_hours = horizon_hours
        self.stride = stride

    def fetch(self) -> list[dict[str, Any]]:
        """The forecast for every sampled cell, for the next two days."""
        cells = forecast_cells(self.stride)
        if not cells:
            return []

        # One issued_at for the whole run. It is the identity of this forecast
        # as a single object: hours from the same run must not be separable by
        # a few seconds of wall clock, or "the newest run" stops being a
        # well-defined set of rows.
        issued_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = issued_at + timedelta(hours=1)
        end = issued_at + timedelta(hours=self.horizon_hours)

        hours = self.horizon_hours
        budget = max(1, MAX_CELL_HOURS_PER_TICK // hours)
        batch_size = min(self.client.batch_size, budget)

        records: list[dict[str, Any]] = []
        for index in range(0, len(cells), batch_size):
            batch = cells[index:index + batch_size]
            try:
                responses = self.client.fetch_range(
                    [(cell.latitude, cell.longitude) for cell in batch], start, end
                )
            except HourlyProviderError as error:
                # A forecast is an outlook, not a measurement: the half already
                # fetched is worth storing, and the next tick in six hours
                # supersedes all of it anyway. Failing the whole run to protect
                # a partial national picture would trade a usable forecast for
                # no forecast.
                logger.warning(
                    "weather_forecast: stopping after %s cells, provider said %s",
                    index, error.category,
                )
                break
            records.extend(self._records(batch, responses, issued_at))
        return records

    def _records(self, cells, responses, issued_at: datetime) -> list[dict[str, Any]]:
        """Turn provider responses into stored readings, one per cell and hour."""
        records = []
        for cell, response in zip(cells, responses):
            hourly = response["hourly"]
            for position, stamp in enumerate(hourly["time"]):
                valid_at = datetime.fromisoformat(stamp)
                if valid_at.tzinfo is None:
                    valid_at = valid_at.replace(tzinfo=timezone.utc)
                values = {
                    variable: series[position]
                    for variable, series in hourly.items()
                    if variable != "time"
                }
                # An hour the provider could not fill is not a forecast of
                # nothing; skip it so a gap stays a gap.
                if all(value is None for value in values.values()):
                    continue
                records.append({
                    "cell_id": cell.cell_id,
                    "latitude": cell.latitude,
                    "longitude": cell.longitude,
                    "observed_at": valid_at,
                    "issued_at": issued_at,
                    "payload": {
                        "provider": "open-meteo",
                        "lead_hours": round((valid_at - issued_at).total_seconds() / 3600),
                        **values,
                    },
                })
        return records
