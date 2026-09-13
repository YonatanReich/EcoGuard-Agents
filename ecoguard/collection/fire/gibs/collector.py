"""MODIS NDVI for every service-area cell: whether the fuel is alive.

`surface_cells` says what grows where, and that never changes. It cannot say
whether the grass is green or cured, and those are different fires — the same
cell of grassland carries a slow creeping burn in March and a fast run in
August. Land cover is the fuel's identity; this is its state.

NDVI is the standard proxy. It is not fuel moisture and should not be reported
as such: it measures canopy greenness, which tracks live fuel moisture well in
herbaceous fuels and poorly under a closed evergreen canopy, where the canopy
stays green over fully cured understorey. Use it as one input, not as an
answer.

Source is NASA GIBS, which serves the MODIS 8-day composite as an open WMS with
no key and no registration — the same arrangement as the EFFIS Fire Weather
Index raster, and this collector follows the same shape: fetch one image over
the country, map pixel colours back through the published legend, sample per
cell. The colour round trip costs a little precision (the legend bins NDVI at
about 0.005) and that is far finer than the question being asked of it.

Eight-day compositing is deliberate on MODIS's part, not a limitation here:
a daily NDVI is mostly cloud and view-angle noise, and vegetation does not
change meaningfully in a day. The composite is republished daily as it rolls,
so a daily tick keeps the freshest one.
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import requests
from PIL import Image

from ecoguard.collection.base import BaseCollector, service_area_cells

logger = logging.getLogger(__name__)

WMS_ENDPOINT = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
COLORMAP_URL = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_NDVI.xml"
LAYER = "MODIS_Terra_NDVI_8Day"

# One pixel per cell would alias; a few pixels per 5 km cell lets the sample be
# the cell's centre rather than whichever pixel a rounding error picked.
RASTER_WIDTH = 1024
PADDING_DEGREES = 0.05
TIMEOUT_SECONDS = 90

# The composite is published with a lag. Walk back until a day returns real
# data rather than guessing the exact publication schedule.
MAX_LOOKBACK_DAYS = 12


class VegetationProviderError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def colour_to_ndvi() -> dict[tuple[int, int, int], float]:
    """The published legend, inverted: RGB back to the NDVI bin's midpoint.

    Fetched rather than transcribed. A legend copied into source is a legend
    that silently goes stale when the provider re-palettes the layer, and the
    failure mode is not an error — it is plausible wrong numbers.

    Transparent entries are no-data (cloud, water, no retrieval) and are left
    out, so an unmatched colour reads as absent instead of as an NDVI of zero,
    which is a real value meaning bare ground.
    """
    response = requests.get(COLORMAP_URL, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)

    mapping: dict[tuple[int, int, int], float] = {}
    for entry in root.iter("ColorMapEntry"):
        if (entry.get("transparent") or "false").lower() == "true":
            continue
        rgb, bounds = entry.get("rgb"), entry.get("value")
        if not rgb or not bounds:
            continue
        try:
            red, green, blue = (int(part) for part in rgb.split(","))
            low, high = (float(part) for part in bounds.strip("[]()").split(","))
        except ValueError:
            continue
        mapping[(red, green, blue)] = round((low + high) / 2, 4)

    if not mapping:
        raise VegetationProviderError("GIBS colormap contained no usable entries")
    return mapping


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

    EPSG:4326 WMS output is plate carree, so this is a linear map. The image
    origin is the north-west corner, hence the inverted latitude term.
    """
    west, south, east, north = bounds
    width, height = size
    x = int((longitude - west) / (east - west) * width)
    y = int((north - latitude) / (north - south) * height)
    return min(max(x, 0), width - 1), min(max(y, 0), height - 1)


class VegetationCollector(BaseCollector):
    source = "vegetation"

    def __init__(self, session: Any | None = None, now: Any = None):
        self.session = session or requests.Session()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _fetch_raster(self, bounds, day: datetime) -> Image.Image:
        west, south, east, north = bounds
        height = max(1, int(RASTER_WIDTH * (north - south) / (east - west)))
        response = self.session.get(
            WMS_ENDPOINT,
            params={
                "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
                "LAYERS": LAYER, "CRS": "EPSG:4326",
                # WMS 1.3.0 orders EPSG:4326 as lat,lon — not lon,lat. Getting
                # this backwards returns a valid image of the wrong place.
                "BBOX": f"{south},{west},{north},{east}",
                "WIDTH": str(RASTER_WIDTH), "HEIGHT": str(height),
                "FORMAT": "image/png", "TIME": day.strftime("%Y-%m-%d"),
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if "image" not in (response.headers.get("Content-Type") or ""):
            raise VegetationProviderError("GIBS returned a service exception, not an image")
        return Image.open(io.BytesIO(response.content)).convert("RGB")

    def fetch(self) -> list[dict[str, Any]]:
        bounds = area_bounds()
        legend = colour_to_ndvi()
        cells = service_area_cells()
        today = self._now().replace(hour=0, minute=0, second=0, microsecond=0)

        for age in range(MAX_LOOKBACK_DAYS):
            day = today - timedelta(days=age)
            image = self._fetch_raster(bounds, day)
            records = self._sample(image, bounds, cells, day, legend)
            if records:
                logger.info("vegetation: %s composite for %s", LAYER, day.date())
                return records
            # An all-transparent image is what GIBS returns for a date whose
            # composite is not published yet, so it is a reason to step back a
            # day rather than an error.

        raise VegetationProviderError(
            f"no {LAYER} composite with data in the last {MAX_LOOKBACK_DAYS} days"
        )

    def _sample(self, image, bounds, cells, day: datetime, legend) -> list[dict[str, Any]]:
        pixels = image.load()
        records = []
        for cell in cells:
            x, y = pixel_for(cell.latitude, cell.longitude, bounds, image.size)
            ndvi = legend.get(tuple(pixels[x, y]))
            if ndvi is None:
                # Cloud, water, or no retrieval. Storing it would occupy the
                # cell's slot for the day and lock out a real value.
                continue
            records.append({
                "cell_id": cell.cell_id,
                "latitude": cell.latitude,
                "longitude": cell.longitude,
                "observed_at": day,
                "payload": {
                    "source": "NASA GIBS",
                    "layer": LAYER,
                    "index": "NDVI",
                    "composite_days": 8,
                    "ndvi": ndvi,
                },
            })
        return records
