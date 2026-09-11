"""The shared collector wrapper, and the grid every collector writes against.

A collector fetches raw data and stores it. It does not detect, filter,
interpret or enrich — that is detection, and it reads these rows later.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Any

from ecoguard.database.locks import single_flight
from ecoguard.database.repositories.collector_runs import log_finish, log_start
from ecoguard.database.repositories.observations import upsert_observations
from services.grid_manager import (
    GRID_RESOLUTION_KM,
    ISRAEL_RISK_BOUNDS,
    LATITUDE_KM_PER_DEGREE,
    LONGITUDE_KM_PER_DEGREE_AT_EQUATOR,
    GridCell,
    generate_grid,
)
from services.service_area import ServiceArea

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def service_area_cells() -> tuple[GridCell, ...]:
    """The 5 km cells inside the operational area — about 1,200 of them.

    Cached because the point-in-polygon sweep over the full 2,848-cell grid
    takes a moment and the answer only changes when the GeoJSON does.
    """
    area = ServiceArea()
    return tuple(
        cell for cell in generate_grid()
        if area.includes_cell(cell.latitude, cell.longitude)
    )


@lru_cache(maxsize=1)
def _cells_by_position() -> dict[tuple[int, int], GridCell]:
    return {(cell.grid_row, cell.grid_col): cell for cell in service_area_cells()}


def cell_for(latitude: float, longitude: float) -> str | None:
    """Return the id of the service-area cell containing a point, or None.

    Inverts generate_grid's row-major layout rather than scanning the grid,
    then confirms the result against the generated cells — so a point outside
    the operational area returns None instead of an id that does not exist.
    """
    west, south, _, _ = ISRAEL_RISK_BOUNDS
    latitude_step = GRID_RESOLUTION_KM / LATITUDE_KM_PER_DEGREE
    row = math.floor((latitude - south) / latitude_step)
    if row < 0:
        return None

    # The longitude step is computed at the row's own centre latitude, exactly
    # as generate_grid does, so cells stay square as you move north.
    row_latitude = south + (row + 0.5) * latitude_step
    longitude_step = GRID_RESOLUTION_KM / (
        LONGITUDE_KM_PER_DEGREE_AT_EQUATOR * math.cos(math.radians(row_latitude))
    )
    column = math.floor((longitude - west) / longitude_step)
    if column < 0:
        return None

    cell = _cells_by_position().get((row, column))
    return cell.cell_id if cell else None


class BaseCollector:
    """Fetch, store, and record the outcome. Only fetch() differs per source."""

    source: str = ""

    def fetch(self) -> list[dict[str, Any]]:
        """Return raw records, each with cell_id, observed_at and payload.

        latitude and longitude are optional; a source that does not know where
        a reading came from leaves them out and location is stored as NULL.
        """
        raise NotImplementedError

    def run(self) -> None:
        """Never raises. A failed collector is one stale layer, not an outage.

        This is the single most important property of the collection layer: the
        scheduler thread must survive every provider outage, credential expiry
        and malformed response any of the four sources can produce.
        """
        try:
            with single_flight(f"collect_{self.source}") as acquired:
                if not acquired:
                    logger.info("%s collector: previous run still going, skipping tick", self.source)
                    return
                run_id = log_start(self.source)
                try:
                    written = upsert_observations(self.source, self.fetch())
                    log_finish(run_id, status="ok", rows_written=written)
                    logger.info("%s collector: %s new observations", self.source, written)
                except Exception as error:
                    log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
                    logger.exception("%s collector failed", self.source)
        except Exception:
            # The database itself is unreachable, so there is nowhere to write a
            # failed row. Log and return; the next tick tries again.
            logger.exception("%s collector could not reach the database", self.source)
