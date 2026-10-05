"""Download the measured evidence for the historical fire demo.

Run once; the output is committed so the demo never depends on two archives
being reachable on the day it is shown:

    python -m ecoguard.demo.scenarios.fetch_historical_fires

Two sources, both the archives of providers the live collectors already use:

  NASA FIRMS   the area endpoint with a start date returns the archived pixels
               for that day, per product. 2010 predates VIIRS (2012) and the
               Meteosat feed, so Carmel has MODIS only - that is the evidence
               that existed, not a choice.
  Open-Meteo   the same hourly variables the weather collector stores, at each
               cell centroid. For 2022 onwards the historical-forecast endpoint
               replays the best-match model the live collector reads. 2010 is
               only covered by the ERA5 reanalysis, a 25 km grid that smooths
               the ridge-top wind, so Carmel's wind is weaker here than the
               "strong easterly" every account describes.

The news items are not fetched here. They were collected by hand from the
outlets' archives and live in `historical_fires_news.json` with their URLs.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from ecoguard.collectors.shared.open_meteo.client import HOURLY_VARIABLES
from ecoguard.shared.cells import cell_for, service_area_cells

OUTPUT = Path(__file__).with_name("historical_fires_data.json")
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{days}/{start}"
ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# Archive product -> the near-real-time product the live collector would have
# stored the same pixel under. The detector reads `firms_source` to pick a
# confidence scale and a pixel size, so the label has to be the live one.
LIVE_NAME = {
    "MODIS_SP": "MODIS_NRT",
    "VIIRS_SNPP_SP": "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_SP": "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT": "VIIRS_NOAA21_NRT",
    "GOES_NRT": "GOES_NRT",
}

FIRES = {
    "carmel_2010": {
        "bbox": (34.90, 32.62, 35.15, 32.82),  # west, south, east, north
        "day": date(2010, 12, 2),
        "days": 2,
        "products": ("MODIS_SP",),
    },
    "jerusalem_2025": {
        "bbox": (34.88, 31.70, 35.20, 31.92),
        "day": date(2025, 4, 30),
        "days": 2,
        "products": (
            "GOES_NRT", "MODIS_SP", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_SP",
        ),
    },
}


def firms_pixels(key: str, fire: dict) -> list[dict]:
    """Every archived pixel in the fire's box, in the collector's pixel shape."""
    west, south, east, north = fire["bbox"]
    pixels = []
    for product in fire["products"]:
        url = FIRMS_URL.format(
            key=key, source=product, bbox=f"{west},{south},{east},{north}",
            days=fire["days"], start=fire["day"].isoformat(),
        )
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        for row in csv.DictReader(io.StringIO(response.text)):
            pixels.append({
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "acquisition_date": row["acq_date"],
                "acquisition_time": row["acq_time"],
                "satellite": row["satellite"],
                "instrument": row["instrument"],
                "confidence": row["confidence"],
                "frp": float(row["frp"]),
                "daynight": row["daynight"],
                "firms_source": LIVE_NAME[product],
            })
    return pixels


def weather_hours(fire: dict) -> dict[str, list[dict]]:
    """Hourly archive weather for every service-area cell in the fire's box."""
    west, south, east, north = fire["bbox"]
    cells = [
        cell for cell in service_area_cells()
        if south <= cell.latitude <= north and west <= cell.longitude <= east
    ]
    start = fire["day"] - timedelta(days=1)
    end = fire["day"] + timedelta(days=fire["days"] - 1)
    url = HISTORICAL_FORECAST_URL if fire["day"].year >= 2022 else ERA5_URL
    response = requests.get(url, params={
        "latitude": ",".join(f"{cell.latitude:.5f}" for cell in cells),
        "longitude": ",".join(f"{cell.longitude:.5f}" for cell in cells),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "UTC",
    }, timeout=120)
    response.raise_for_status()
    body = response.json()
    body = body if isinstance(body, list) else [body]

    hours: dict[str, list[dict]] = {}
    for cell, series in zip(cells, body):
        hourly = series["hourly"]
        hours[cell.cell_id] = [
            {
                "observed_at": f"{stamp}:00Z",
                **{variable: hourly[variable][index] for variable in HOURLY_VARIABLES},
            }
            for index, stamp in enumerate(hourly["time"])
        ]
    return hours


def main() -> None:
    """Fetch both fires and write the committed data file."""
    load_dotenv()
    key = os.environ["NASA_FIRMS_API_KEY"]
    output = {"fetched_at": datetime.now(timezone.utc).isoformat(), "fires": {}}
    for name, fire in FIRES.items():
        pixels = firms_pixels(key, fire)
        pixels = [p for p in pixels if cell_for(p["latitude"], p["longitude"])]
        output["fires"][name] = {
            "bbox": fire["bbox"],
            "firms_pixels": pixels,
            "weather": weather_hours(fire),
        }
        print(f"{name}: {len(pixels)} pixels, "
              f"{len(output['fires'][name]['weather'])} weather cells")
        time.sleep(1)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
