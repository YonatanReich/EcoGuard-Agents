"""NASA FIRMS satellite hotspots for the whole service area."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from agents.firms_data_agent import FirmsDataAgent
from ecoguard.collection.base import BaseCollector, cell_for, service_area_cells

# FIRMS near-real-time data arrives hours after the overpass and occasionally
# straddles a UTC day boundary, so two days are requested every tick. The
# unique constraint makes the overlap free.
DAY_RANGE = 2
SOURCE = "VIIRS_NOAA20_NRT"


def _observed_at(hotspot: dict[str, Any]) -> datetime:
    """FIRMS reports the overpass as a UTC date plus an HHMM time."""
    acquisition_time = str(hotspot["acquisition_time"]).zfill(4)
    return datetime.strptime(
        f"{hotspot['acquisition_date']} {acquisition_time}", "%Y-%m-%d %H%M"
    ).replace(tzinfo=timezone.utc)


def _service_area_box() -> tuple[float, float, float]:
    """Centre and half-span covering every service-area cell."""
    cells = service_area_cells()
    latitudes = [cell.latitude for cell in cells]
    longitudes = [cell.longitude for cell in cells]
    centre_latitude = (min(latitudes) + max(latitudes)) / 2
    centre_longitude = (min(longitudes) + max(longitudes)) / 2
    # FirmsDataAgent takes one symmetric delta, so the wider span sets it. The
    # box then over-reaches east and west; those hotspots are dropped below.
    delta = max(
        (max(latitudes) - min(latitudes)) / 2,
        (max(longitudes) - min(longitudes)) / 2,
    )
    return centre_latitude, centre_longitude, delta


def group_hotspots(hotspots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One observation per cell per overpass, carrying every pixel in it.

    A 5 km cell holds roughly 180 VIIRS pixels, and a real fire lights several
    at once. Storing one row per pixel would make them collide on the unique
    constraint and silently lose all but the first.
    """
    grouped: dict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
    for hotspot in hotspots:
        cell_id = cell_for(hotspot["latitude"], hotspot["longitude"])
        if cell_id is None:
            continue  # outside the operational area; the bounding box overshoots it
        grouped[(cell_id, _observed_at(hotspot))].append(hotspot)

    cells = {cell.cell_id: cell for cell in service_area_cells()}
    records = []
    for (cell_id, observed_at), pixels in grouped.items():
        cell = cells[cell_id]
        records.append({
            "cell_id": cell_id,
            # The cell centroid, not the pixel mean: it is deterministic for a
            # given cell_id, so a re-fetch that adds a pixel does not imply a
            # location the stored row can no longer be updated to.
            "latitude": cell.latitude,
            "longitude": cell.longitude,
            "observed_at": observed_at,
            "payload": {
                "satellite_source": SOURCE,
                "hotspot_count": len(pixels),
                "hotspots": pixels,
            },
        })
    return records


class FirmsCollector(BaseCollector):
    source = "firms"

    def __init__(self, agent: FirmsDataAgent | None = None):
        self.agent = agent or FirmsDataAgent()

    def fetch(self) -> list[dict[str, Any]]:
        """One bounding-box call for the entire service area.

        Per-cell calls would mean ~1,200 requests per tick for a dataset whose
        pixels arrive roughly three hours apart. The API takes an area, so ask
        it for the area.
        """
        latitude, longitude, delta = _service_area_box()
        response = self.agent.fetch_hotspots(
            latitude=latitude,
            longitude=longitude,
            delta=delta,
            source=SOURCE,
            day_range=DAY_RANGE,
        )
        return group_hotspots(response["fire_satellite_data"]["hotspots"])
