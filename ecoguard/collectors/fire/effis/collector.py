"""GWIS/EFFIS Fire Weather Index for every service-area cell."""

from __future__ import annotations

import io
from datetime import date, datetime, time, timezone
from typing import Any

import requests
from PIL import Image

from ecoguard.collectors.fire.effis.danger import FireDangerAgent
from ecoguard.collectors.base import BaseCollector, service_area_cells

# The FWI raster is a categorised visualisation, so resolution only has to beat
# the 5 km grid. 512 px across the country is roughly 300 m per pixel.
RASTER_WIDTH = 512
PADDING_DEGREES = 0.05


def area_bounds() -> tuple[float, float, float, float]:
    """west, south, east, north covering every cell, padded by half a cell."""
    cells = service_area_cells()
    latitudes = [cell.latitude for cell in cells]
    longitudes = [cell.longitude for cell in cells]
    return (
        min(longitudes) - PADDING_DEGREES,
        min(latitudes) - PADDING_DEGREES,
        max(longitudes) + PADDING_DEGREES,
        max(latitudes) + PADDING_DEGREES,
    )


def pixel_for(
    latitude: float,
    longitude: float,
    bounds: tuple[float, float, float, float],
    size: tuple[int, int],
) -> tuple[int, int]:
    """Map a coordinate onto the raster.

    EPSG:4326 WMS output is plate carrée, so this is a linear map. The image
    origin is the north-west corner, hence the inverted latitude term.
    """
    west, south, east, north = bounds
    width, height = size
    x = int((longitude - west) / (east - west) * width)
    y = int((north - latitude) / (north - south) * height)
    return min(max(x, 0), width - 1), min(max(y, 0), height - 1)


class FireWeatherCollector(BaseCollector):
    source = "fire_weather"

    def __init__(self, agent: FireDangerAgent | None = None):
        """Build the collector with its provider client."""
        # FireDangerAgent's legend mapping is the valuable part and is reused
        # unchanged. Its fetch is per-point, which would be ~1,200 WMS calls a
        # tick; one raster covering the country answers all of them.
        self.agent = agent or FireDangerAgent()

    def fetch_area_raster(self, bounds: tuple[float, float, float, float], day: date) -> Image.Image:
        """Download the fire-danger image covering this area for one day."""
        west, south, east, north = bounds
        height = round(RASTER_WIDTH * (north - south) / (east - west))
        response = requests.get(
            self.agent.base_url,
            params={
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetMap",
                "LAYERS": self.agent.layer,
                "STYLES": "",
                "SRS": "EPSG:4326",
                "BBOX": f"{west},{south},{east},{north}",
                "WIDTH": RASTER_WIDTH,
                "HEIGHT": height,
                "FORMAT": "image/png",
                "TRANSPARENT": "false",
                "TIME": day.isoformat(),
            },
            timeout=60,
        )
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")

    def fetch(self) -> list[dict[str, Any]]:
        """One raster, sampled at each cell centroid.

        FWI is a daily product, so observed_at is midnight UTC of the raster's
        day and every tick that day writes the same identities — the unique
        constraint turns all but the first into a no-op.
        """
        bounds = area_bounds()
        day = datetime.now(timezone.utc).date()
        raster = self.fetch_area_raster(bounds, day)
        observed_at = datetime.combine(day, time.min, tzinfo=timezone.utc)

        records = []
        for cell in service_area_cells():
            x, y = pixel_for(cell.latitude, cell.longitude, bounds, raster.size)
            classification = self.agent.classify_fwi_pixel(raster.getpixel((x, y)))
            if classification["danger_level"] == "unknown":
                # No classified FWI data at this point — sea, or the day's
                # raster is not published yet. Storing it would occupy the
                # cell's slot for the day and lock out the real value.
                continue
            records.append({
                "cell_id": cell.cell_id,
                "latitude": cell.latitude,
                "longitude": cell.longitude,
                "observed_at": observed_at,
                "payload": {"source": "GWIS/EFFIS", "index": "FWI", **classification},
            })
        return records
