"""NASA FIRMS satellite hotspots for the whole service area."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import logging

from ecoguard.collectors.fire.firms.client import FirmsDataAgent, FirmsProviderError
from ecoguard.collectors.base import BaseCollector, cell_for, service_area_cells

logger = logging.getLogger(__name__)

# FIRMS near-real-time data arrives hours after the overpass and occasionally
# straddles a UTC day boundary, so two days are requested every tick. The
# unique constraint makes the overlap free.
DAY_RANGE = 2

# Every near-real-time product FIRMS publishes for this region, not one of
# them. They are separate satellites on separate overpasses: NOAA-20, NOAA-21
# and Suomi-NPP fly the same orbital plane about fifty minutes apart, and the
# two MODIS instruments cross at different hours entirely. Asking for one was
# discarding most of the day's looks at the country for no saving — it is the
# same API key, the same bounding box, and one extra request each.
#
# MODIS is 1 km against VIIRS's 375 m and will miss small fires the VIIRS
# products catch. It is kept because a coarse detection at an hour nothing else
# flies over still beats no detection, and the pixel footprint travels in the
# payload so a consumer can weigh it.
# FIRMS calls the geostationary feed GOES_NRT, which is a misnomer for this
# region: over Israel it returns Meteosat (Met9, Met10, Met12 — the last being
# MTG-I1). GOES itself sits over the Americas and cannot see us.
#
# It is the most valuable product in this list and the reason is timing. The
# polar satellites cross a few times a day, so a fire that starts just after an
# overpass waits hours to be seen. Meteosat is parked over 0° longitude with
# Israel permanently in view and reports every ten minutes. On the Galilee fire
# of 14 September it detected at 07:08 against VIIRS's 09:58 — nearly three
# hours earlier — and produced 114 detections to VIIRS's 13.
#
# It does not replace the polar products, it complements them: ~1.4 km grid
# against VIIRS's 375 m, so it finds fires early and VIIRS says where they
# actually are. Two independent sources agreeing in one cell is what the
# coordinator is built to reward.
GEOSTATIONARY_SOURCES = ("GOES_NRT",)

SOURCES = (
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP_NRT",
    "MODIS_NRT",
) + GEOSTATIONARY_SOURCES

# The area endpoint caps day_range per product, and not at the same number:
# five for the polar products, two for the geostationary one. Exceeding it is
# an HTTP 400 with "Invalid day range", not a truncated answer.
MAX_DAY_RANGE = {source: 5 for source in SOURCES}
MAX_DAY_RANGE.update({source: 2 for source in GEOSTATIONARY_SOURCES})


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

    Grouping is by cell and time only, deliberately not by satellite. Two
    instruments that see the same cell in the same minute are seeing one fire,
    and that is one observation of it — merging them is the correct answer
    rather than a collision to be worked around. Which satellites contributed
    travels in the payload, so agreement between them stays readable and is
    itself evidence: a hotspot three instruments caught is not the same claim
    as one that only MODIS saw.
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
                "satellite_sources": sorted(
                    {pixel["firms_source"] for pixel in pixels if pixel.get("firms_source")}
                ),
                "hotspot_count": len(pixels),
                "peak_frp_mw": max(
                    (pixel["frp"] for pixel in pixels if pixel.get("frp") is not None),
                    default=None,
                ),
                "hotspots": pixels,
            },
        })
    return records


class FirmsCollector(BaseCollector):
    source = "firms"

    def __init__(
        self,
        agent: FirmsDataAgent | None = None,
        sources: tuple[str, ...] = SOURCES,
    ):
        """Build the collector with its provider client."""
        self.agent = agent or FirmsDataAgent()
        self.sources = sources

    def fetch(self) -> list[dict[str, Any]]:
        """One bounding-box call for the entire service area.

        Per-cell calls would mean ~1,200 requests per tick for a dataset whose
        pixels arrive roughly three hours apart. The API takes an area, so ask
        it for the area.
        """
        latitude, longitude, delta = _service_area_box()
        hotspots: list[dict[str, Any]] = []
        failures: list[str] = []
        for source in self.sources:
            try:
                response = self.agent.fetch_hotspots(
                    latitude=latitude,
                    longitude=longitude,
                    delta=delta,
                    source=source,
                    day_range=DAY_RANGE,
                )
            except Exception as error:
                # One satellite product being down is not a detection outage
                # while three others answered. Losing every look because one
                # endpoint returned 503 is the opposite of why they are all
                # queried.
                failures.append(source)
                logger.warning("firms: %s unavailable (%s)", source, type(error).__name__)
                continue
            for hotspot in response["fire_satellite_data"]["hotspots"]:
                # Tag before merging: after grouping there is no way back to
                # which instrument saw what.
                hotspots.append({**hotspot, "firms_source": source})

        if failures and len(failures) == len(self.sources):
            raise FirmsProviderError(
                f"every FIRMS product failed: {', '.join(failures)}"
            )
        return group_hotspots(hotspots)
