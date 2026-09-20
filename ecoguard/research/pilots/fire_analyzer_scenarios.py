"""Six fabricated incidents, each with a known answer, for exercising the analyser.

Every incident here is shaped exactly as `coordinator/incidents.py` stores one —
same keys, same types, a real `cells` entry from `shared/cells.py`, a signal
list in `CellSignal` form. Nothing about the analyser knows these are made up.

What is fabricated and what is real
-----------------------------------
The **incident** is fabricated: its position, its time, and the satellite
evidence attached to it. The **weather** is stated per scenario, because a
regression fixture cannot depend on what the wind happened to be doing today.

Everything else is read live from the store and is not fabricated at all:

  * land cover and slope, from `surface_cells` (429,876 cells of Copernicus DEM
    and ESA WorldCover),
  * settlement outlines, populations and authority telephone numbers, from
    `towns` (1,168 rows),
  * residents inside the forecast extent, from `population_cells` (315,600
    cells of WorldPop).

So each case asks a real question about real ground under stated conditions,
and `expect` records what the answer has to be for the analyser to be working.

The six
-------
They are chosen to separate behaviours that could otherwise hide each other:

  1. **negev_khamsin** — shrubland at Lahav under a dry east wind. Fast spread,
     settlements reached. The case the analyser exists for.
  2. **petah_tikva_building** — a residential block. There is no wildland run
     here; the test is that it still names Petah Tikva and its authority rather
     than reporting "open ground", and that it flags the built-up share.
  3. **carmel_east_wind** — pine on the Carmel with Haifa downwind. Big
     population, steep ground, the 2010 geometry.
  4. **judean_hills_upslope** — the steepest ground in the set, light wind. The
     fire should run *up* the hill rather than with the breeze.
  5. **dead_sea_bare** — a detection where the surface grid has a genuine hole.
     Must degrade honestly, not silently report calm.
  6. **galilee_winter_wet** — the same kind of fuel as (3) in January rain.
     Must stall for a *different, named* reason than (5); "no fuel" and "too
     wet to burn" are different facts and an operator acts on them differently.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ecoguard.shared.cells import cell_for

# Two seasons, stated once. Summer is a real khamsin: the hot, desiccating east
# wind that drives every large fire Israel has had. Winter is the wet extreme.
SUMMER = datetime(2026, 8, 14, 13, 40, tzinfo=timezone.utc)
WINTER = datetime(2026, 1, 22, 9, 15, tzinfo=timezone.utc)


def _incident(
    identifier: str,
    latitude: float,
    longitude: float,
    observed_at: datetime,
    *,
    peak_frp_mw: float,
    hotspots: int,
    satellites: list[str],
    signal_count: int = 1,
    precision_m: float = 375.0,
) -> dict[str, Any]:
    """One incident in the exact shape the coordinator stores.

    `cells` is resolved through the real grid rather than written by hand, so a
    scenario cannot drift from the geometry the rest of the system uses.
    """
    cell = cell_for(latitude, longitude)
    return {
        "id": identifier,
        "status": "open",
        "primary_hazard": "fire",
        "hazards": ["fire"],
        "queues": ["emergency"],
        "cells": [cell] if cell else [],
        "latitude": latitude,
        "longitude": longitude,
        "precision_m": precision_m,
        "location_method": "frp_weighted_centroid",
        "first_seen_at": observed_at - timedelta(minutes=50),
        "last_signal_at": observed_at,
        "closed_at": None,
        "signal_count": signal_count,
        "peak_rarity": 1.0,
        "links": [],
        "signals": [
            {
                "cell_id": cell,
                "observed_at": observed_at.isoformat(),
                "hazard": "fire",
                "variable": "frp",
                "value": peak_frp_mw,
                "unit": "MW",
                "source": "firms",
                "rarity": 1.0,
                "direction": "high",
                "confidence": 0.9 if len(satellites) > 1 else 0.8,
                "severity": None,
                "evidence": {
                    "hotspot_count": hotspots,
                    "satellites": satellites,
                    "recent_detections": [],
                },
            }
        ],
    }


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "key": "negev_khamsin",
        "title": "Wildfire in Negev shrubland under a khamsin",
        "plain_english": (
            "Satellite picks up a fire in the Lahav shrubland of the northern "
            "Negev on a 41 C August afternoon, with a dry 50 km/h east wind. "
            "Lahav, Lehavim and Dvir lie to the west of it."
        ),
        "incident": _incident(
            "INC-20260814-0031", 31.3790, 34.8500, SUMMER,
            peak_frp_mw=88.4, hotspots=11,
            satellites=["VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT", "GOES_NRT"],
            signal_count=4,
        ),
        "environment": {
            "temperature_c": 41.0, "humidity_percent": 11.0,
            "wind_speed_kmh": 50.0, "wind_direction_deg": 95.0,
        },
        "expect": {
            "status": "ok",
            "spreads": True,
            "heading_roughly": "west",
            "names_settlements": ["Lehavim", "Rahat"],
            # Lahav sits at bearing 090 from the ignition point — directly into
            # an east wind. A fire running west must not reach it, and naming it
            # anyway would mean the ellipse is not oriented at all. This began
            # as an expectation that Lahav *would* be hit, written from its
            # distance without checking its bearing; the analyser was right and
            # the expectation was wrong, so it is inverted here into the
            # stronger test.
            "excludes_settlements": ["Lahav"],
            "evacuation_nonempty": True,
            "note": (
                "Continuous shrubland, dry, windy — this must run and reach the "
                "downwind towns while leaving the upwind one alone."
            ),
        },
    },
    {
        "key": "petah_tikva_building",
        "title": "Residential block alight in Petah Tikva",
        "plain_english": (
            "A fire in a residential building in central Petah Tikva on a "
            "muggy July evening. It is a structure fire in a dense city; there "
            "is no wildland for it to run through."
        ),
        "incident": _incident(
            "INC-20260701-0012", 32.0909, 34.8764,
            datetime(2026, 7, 1, 18, 20, tzinfo=timezone.utc),
            peak_frp_mw=6.1, hotspots=1, satellites=["VIIRS_NOAA21_NRT"],
            precision_m=375.0,
        ),
        "environment": {
            "temperature_c": 31.0, "humidity_percent": 58.0,
            "wind_speed_kmh": 14.0, "wind_direction_deg": 275.0,
        },
        "expect": {
            "status": "any",
            "spreads": False,
            "names_origin": "Petah Tikva",
            "flags_built_up": True,
            "note": (
                "Must name Petah Tikva and its authority, must flag the "
                "built-up share, and must not imply a wildland run through a city."
            ),
        },
    },
    {
        "key": "carmel_east_wind",
        "title": "Carmel pine forest, east wind toward Haifa",
        "plain_english": (
            "The 2010 geometry: fire in the Carmel forest with a hot, dry east "
            "wind pushing it downslope toward Beit Oren, Nesher and Haifa."
        ),
        "incident": _incident(
            "INC-20260814-0033", 32.7350, 35.0250, SUMMER,
            peak_frp_mw=142.7, hotspots=23,
            satellites=["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT",
                        "VIIRS_SNPP_NRT", "MODIS_NRT", "GOES_NRT"],
            signal_count=9,
        ),
        "environment": {
            "temperature_c": 39.0, "humidity_percent": 14.0,
            "wind_speed_kmh": 45.0, "wind_direction_deg": 100.0,
        },
        "expect": {
            "status": "ok",
            "spreads": True,
            "heading_roughly": "west",
            "names_settlements": ["Beit Oren"],
            "large_population_exposed": True,
            "note": "Dense tree cover, strong wind, a major city within reach.",
        },
    },
    {
        "key": "judean_hills_upslope",
        "title": "Judean hills, light wind on steep ground",
        "plain_english": (
            "Fire on a steep wooded slope west of Jerusalem with only a light "
            "breeze. With almost no wind, terrain should decide the direction: "
            "fire runs uphill."
        ),
        "incident": _incident(
            "INC-20260814-0035", 31.7900, 35.0600, SUMMER,
            peak_frp_mw=31.2, hotspots=5,
            satellites=["VIIRS_SNPP_NRT", "GOES_NRT"], signal_count=2,
        ),
        "environment": {
            "temperature_c": 34.0, "humidity_percent": 28.0,
            "wind_speed_kmh": 5.0, "wind_direction_deg": 200.0,
        },
        "expect": {
            "status": "ok",
            "spreads": True,
            "names_settlements": ["Shoresh"],
            "note": (
                "Slope is 17 degrees mean, 35 degrees steepest. With a 5 km/h "
                "breeze the slope term should dominate the heading."
            ),
        },
    },
    {
        "key": "dead_sea_bare",
        "title": "Detection on the Dead Sea shore, no surface data",
        "plain_english": (
            "A hotspot on the Dead Sea shore, where the land-cover grid has a "
            "genuine hole — the survey maps no vegetation there at all."
        ),
        "incident": _incident(
            "INC-20260814-0037", 31.0659, 35.4359, SUMMER,
            peak_frp_mw=12.9, hotspots=2, satellites=["MODIS_NRT"],
            precision_m=1000.0,
        ),
        "environment": {
            "temperature_c": 44.0, "humidity_percent": 9.0,
            "wind_speed_kmh": 22.0, "wind_direction_deg": 180.0,
        },
        "expect": {
            "status": "stalled_or_skipped",
            "spreads": False,
            "unscored": True,
            "note": (
                "Must degrade honestly: no score, no zero, and a report that "
                "says the absence is about the data and not about the fire."
            ),
        },
    },
    {
        "key": "galilee_winter_wet",
        "title": "Upper Galilee woodland in January rain",
        "plain_english": (
            "The same kind of fuel as the Carmel case, in the wet season: "
            "9 C, 95% humidity, saturated fuel. Nothing should carry."
        ),
        "incident": _incident(
            "INC-20260122-0004", 33.1200, 35.5700, WINTER,
            peak_frp_mw=4.3, hotspots=1, satellites=["VIIRS_NOAA20_NRT"],
        ),
        "environment": {
            "temperature_c": 9.0, "humidity_percent": 95.0,
            "wind_speed_kmh": 18.0, "wind_direction_deg": 250.0,
        },
        "expect": {
            "status": "stalled",
            "spreads": False,
            "unscored": True,
            "distinct_reason_from": "dead_sea_bare",
            "note": (
                "Must stall for wetness, named differently from the no-data "
                "case. 'Nothing to burn' and 'too wet to burn' are different "
                "facts and are acted on differently."
            ),
        },
    },
)
