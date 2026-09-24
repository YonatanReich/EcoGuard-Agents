"""Demo B, phase 1: four emergency events that exercise incident identity.

The scenario follows Demo A's contract: it stores only observations in the
same shapes as the real collectors.  The ordinary detection, coordination,
analysis, planning, allocation and projection pipeline must turn them into
events.

This first phase concentrates on four authored events: an expanding fire that
crosses a grid boundary, a second nearby fire that must remain independent, an
escalating flash flood, and one earthquake sequence containing two
aftershocks.  A small amount of structured noise pins the corresponding
suppression boundaries.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session


# --------------------------------------------------------------------------
# The events, authored
# --------------------------------------------------------------------------

JERUSALEM_HILLS = (31.7800, 35.1200)
JERUSALEM_HILLS_SPREAD = (31.8000, 35.1500)
BEIT_SHEMESH = (31.7400, 34.9900)
ASHALIM = (31.0659, 35.3301)
TIBERIAS = (32.7900, 35.5300)
TIBERIAS_AFTERSHOCK = (32.8000, 35.5300)

# The first two cells touch, so their fire signals must be folded into B1.
# Beit Shemesh is several columns away: close enough to challenge a naive
# radius matcher, but outside the coordinator's one-cell identity boundary.
JERUSALEM_HILLS_CELL = "risk-05000m-r0052-c0017"
JERUSALEM_HILLS_SPREAD_CELL = "risk-05000m-r0053-c0017"
BEIT_SHEMESH_CELL = "risk-05000m-r0051-c0014"
ASHALIM_CELL = "risk-05000m-r0036-c0021"
TIBERIAS_CELL = "risk-05000m-r0074-c0024"
TIBERIAS_AFTERSHOCK_CELL = "risk-05000m-r0075-c0024"


GROUND_TRUTH: list[dict[str, Any]] = [
    {
        "id": "B1",
        "event": (
            "A growing wildfire in the Jerusalem Hills spreads into an "
            "adjacent grid cell."
        ),
        "hazard": "fire",
        "latitude": JERUSALEM_HILLS[0],
        "longitude": JERUSALEM_HILLS[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 3.0,
        "expect_min_signals": 2,
        "expect_notes": (
            "Three FIRMS overpasses show rising FRP and a later detection in "
            "the touching northern cell. The two reportable cell signals must "
            "be one incident, not duplicate fires. Hot, dry, windy weather is "
            "available to the fire analysis. If risk analysis is unavailable, "
            "the event remains visible but receives no automatic allocation."
        ),
    },
    {
        "id": "B2",
        "event": (
            "A separate fire near Beit Shemesh burns at the same time as B1."
        ),
        "hazard": "fire",
        "latitude": BEIT_SHEMESH[0],
        "longitude": BEIT_SHEMESH[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 3.0,
        "expect_min_signals": 1,
        "expect_notes": (
            "This fire is geographically near B1 but its grid cell is not "
            "adjacent. It must remain a second fire incident. If risk analysis "
            "is unavailable, it remains visible without automatic allocation."
        ),
    },
    {
        "id": "B3",
        "event": (
            "A Nahal Ashalim flash flood rapidly rises above Q20."
        ),
        "hazard": "flood",
        "latitude": ASHALIM[0],
        "longitude": ASHALIM[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 6.0,
        "expect_min_signals": 1,
        "expect_allocation": True,
        "expect_allocated_units": ["police"],
        "expect_routing": True,
        "expect_notes": (
            "After a normal reading, two consecutive readings exceed Q20. "
            "That is one reportable flood update and must open one incident."
        ),
    },
    {
        "id": "B4",
        "event": (
            "A Sea of Galilee earthquake is followed by two nearby aftershocks."
        ),
        "hazard": "earthquake",
        "latitude": TIBERIAS[0],
        "longitude": TIBERIAS[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 4.0,
        "expect_min_signals": 3,
        "expect_allocation": True,
        "expect_allocated_units": ["police"],
        "expect_routing": True,
        "expect_notes": (
            "A magnitude 5.4 mainshock and two reportable aftershocks arrive "
            "within two hours in the same or an adjacent cell. They must form "
            "one incident with three signals, not three incidents."
        ),
    },
]


EXPECTED_BYPRODUCTS: list[dict[str, str]] = [
    {
        "hazard": "fire_weather",
        "why": (
            "The deliberately severe weather supplied as fire-analysis "
            "context can also cross the independent fire-weather detector's "
            "threshold. That advisory has no registered projection handler."
        ),
    },
]


EXPECTED_SILENCE: list[dict[str, str]] = [
    {
        "id": "BN1",
        "noise": "A strong FIRMS hotspot observed three days earlier.",
        "expect": "outside the satellite detector's freshness window",
    },
    {
        "id": "BN2",
        "noise": "One isolated high discharge between two normal readings.",
        "expect": "no flood signal without two consecutive threshold exceedances",
    },
    {
        "id": "BN3",
        "noise": "A local magnitude 3.4 earthquake.",
        "expect": "below the dashboard's magnitude 3.5 threshold",
    },
]


# --------------------------------------------------------------------------
# Evidence derived from those events
# --------------------------------------------------------------------------


def _firms(
    lat: float,
    lon: float,
    frp: float,
    pixels: int,
    *,
    satellite: str = "N20",
) -> dict[str, Any]:
    """One FIRMS overpass, in the exact shape the collector stores."""
    spread = 0.004
    hotspots = [
        {
            "frp": round(frp / pixels, 4),
            "daynight": "D",
            "latitude": round(lat + spread * (index - pixels / 2), 6),
            "longitude": round(lon + spread * (index % 2), 6),
            "satellite": satellite,
            "confidence": "h",
            "instrument": "VIIRS",
            "firms_source": "VIIRS_NOAA20_NRT",
            "acquisition_date": "",
            "acquisition_time": "",
        }
        for index in range(pixels)
    ]
    return {
        "hotspots": hotspots,
        "peak_frp_mw": frp,
        "hotspot_count": pixels,
        "satellite_sources": ["VIIRS_NOAA20_NRT"],
    }


def _weather(
    temperature: float,
    humidity: float,
    wind: float,
    gusts: float,
    direction: float,
) -> dict[str, Any]:
    """One weather reading, in the shape the collector stores."""
    return {
        "rain": 0.0,
        "weather_code": 0.0,
        "precipitation": 0.0,
        "temperature_2m": temperature,
        "wind_gusts_10m": gusts,
        "wind_speed_10m": wind,
        "wind_direction_10m": direction,
        "relative_humidity_2m": humidity,
        "soil_moisture_0_to_7cm": 0.03,
        "vapour_pressure_deficit": 4.6,
        "et0_fao_evapotranspiration": 0.42,
    }


def _gauge(
    station_id: int,
    name_en: str,
    name_he: str,
    lat: float,
    lon: float,
    discharge: float,
    height: float,
    basin: int,
) -> dict[str, Any]:
    """One hydrometric reading with the thresholds production carries."""
    return {
        "stations": [
            {
                "name_en": name_en,
                "name_he": name_he,
                "latitude": lat,
                "longitude": lon,
                "discharge_m3s": discharge,
                "water_height_m": height,
                "drainage_basin_id": basin,
                "source_station_id": station_id,
                "flow_threshold_2y_m3s": 5.0,
                "flow_threshold_5y_m3s": 20.0,
                "flow_threshold_status": "complete_thresholds",
                "flow_threshold_10y_m3s": 48.0,
                "flow_threshold_20y_m3s": 92.0,
                "flow_threshold_50y_m3s": 165.0,
                "flow_threshold_100y_m3s": 240.0,
                "flow_start_water_level_m": 0.06,
            }
        ],
    }


def _earthquake(
    event_id: str,
    observed: datetime,
    lat: float,
    lon: float,
    magnitude: float,
    depth_km: float,
    location_name: str,
) -> dict[str, Any]:
    """One normalized GSI event, in the exact shape the collector stores."""
    return {
        "provider_event_id": event_id,
        "observed_at": observed.isoformat(),
        "latitude": lat,
        "longitude": lon,
        "magnitude": magnitude,
        "depth_km": depth_km,
        "provider": "GSI",
        "raw": {
            "event_id": event_id,
            "author": "GSI",
            "catalog": "GSI",
            "contributor": "GSI",
            "contributor_id": event_id,
            "magnitude_type": "ML",
            "magnitude_author": "GSI",
            "event_location_name": location_name,
            "event_type": "earthquake",
        },
    }


def build_rows(now: datetime) -> list[tuple[str, str, datetime, dict[str, Any]]]:
    """Every observation written as (source, cell, observed_at, payload)."""

    def ago(minutes: int) -> datetime:
        return now - timedelta(minutes=minutes)

    rows: list[tuple[str, str, datetime, dict[str, Any]]] = []

    # --- B1: one growing fire crossing into an adjacent cell --------------
    rows.extend(
        [
            (
                "firms",
                JERUSALEM_HILLS_CELL,
                ago(105),
                _firms(*JERUSALEM_HILLS, 55.0, 1),
            ),
            (
                "firms",
                JERUSALEM_HILLS_CELL,
                ago(62),
                _firms(*JERUSALEM_HILLS, 145.0, 3),
            ),
            (
                "firms",
                JERUSALEM_HILLS_SPREAD_CELL,
                ago(21),
                _firms(*JERUSALEM_HILLS_SPREAD, 235.0, 5),
            ),
            (
                "weather",
                JERUSALEM_HILLS_CELL,
                ago(48),
                _weather(39.0, 12.0, 23.0, 49.0, 285.0),
            ),
        ]
    )

    # --- B2: a concurrent but non-adjacent fire ---------------------------
    rows.extend(
        [
            (
                "firms",
                BEIT_SHEMESH_CELL,
                ago(58),
                _firms(*BEIT_SHEMESH, 48.0, 1, satellite="SNPP"),
            ),
            (
                "firms",
                BEIT_SHEMESH_CELL,
                ago(16),
                _firms(*BEIT_SHEMESH, 88.0, 2, satellite="SNPP"),
            ),
            (
                "weather",
                BEIT_SHEMESH_CELL,
                ago(45),
                _weather(36.5, 18.0, 17.0, 35.0, 300.0),
            ),
        ]
    )

    # BN1: strong, but historical rather than a current fire.
    rows.append(
        (
            "firms",
            "risk-05000m-r0042-c0011",
            now - timedelta(days=3),
            _firms(31.3000, 34.7800, 190.0, 4),
        )
    )

    # --- B3: Ashalim rises from normal flow to two Q20 readings ------------
    for minutes, discharge, height in (
        (86, 0.5, 0.09),
        (30, 98.0, 3.2),
        (7, 132.0, 3.9),
    ):
        rows.append(
            (
                "water_authority_hydrometric_observations",
                ASHALIM_CELL,
                ago(minutes),
                _gauge(
                    378,
                    "Ashalim",
                    "אשלים במעלה",
                    *ASHALIM,
                    discharge,
                    height,
                    65,
                ),
            )
        )

    # BN2: one spike at Ramon, with a normal reading on either side.
    for minutes, discharge, height in (
        (82, 0.2, -0.18),
        (43, 78.0, 1.8),
        (9, 0.3, -0.16),
    ):
        rows.append(
            (
                "water_authority_hydrometric_observations",
                "risk-05000m-r0026-c0012",
                ago(minutes),
                _gauge(
                    58,
                    "Ramon",
                    "רמון",
                    30.6144,
                    34.8601,
                    discharge,
                    height,
                    68,
                ),
            )
        )

    # --- B4: one mainshock and two reportable aftershocks -----------------
    for event_id, minutes, location, cell, magnitude, depth in (
        ("demo-b-gsi-main", 78, TIBERIAS, TIBERIAS_CELL, 5.4, 11.0),
        ("demo-b-gsi-after-1", 46, TIBERIAS, TIBERIAS_CELL, 4.3, 10.5),
        (
            "demo-b-gsi-after-2",
            14,
            TIBERIAS_AFTERSHOCK,
            TIBERIAS_AFTERSHOCK_CELL,
            3.9,
            9.8,
        ),
    ):
        observed = ago(minutes)
        rows.append(
            (
                "gsi_earthquake",
                cell,
                observed,
                _earthquake(
                    event_id,
                    observed,
                    *location,
                    magnitude,
                    depth,
                    "Sea of Galilee Region",
                ),
            )
        )

    # BN3: a genuine local earthquake below the dashboard threshold.
    observed = ago(35)
    rows.append(
        (
            "gsi_earthquake",
            "risk-05000m-r0040-c0021",
            observed,
            _earthquake(
                "demo-b-gsi-below-threshold",
                observed,
                31.2200,
                35.3200,
                3.4,
                14.0,
                "Dead Sea Region",
            ),
        )
    )

    return rows


INSERT = text(
    'INSERT INTO "{schema}".observations '
    "(source, cell_id, location, observed_at, ingested_at, payload) "
    "VALUES (:source, :cell_id, NULL, :observed_at, :ingested_at, "
    "CAST(:payload AS jsonb))"
)


def seed(schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Write Demo B observations into its sandbox schema."""
    moment = now or datetime.now(timezone.utc)
    rows = build_rows(moment)
    statement = text(str(INSERT).replace("{schema}", schema))

    with Session() as session:
        for source, cell_id, observed_at, payload in rows:
            session.execute(
                statement,
                {
                    "source": source,
                    "cell_id": cell_id,
                    "observed_at": observed_at,
                    "ingested_at": moment,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
        session.commit()

    by_source: dict[str, int] = {}
    for source, *_ in rows:
        by_source[source] = by_source.get(source, 0) + 1

    return {
        "observations": len(rows),
        "by_source": by_source,
        "seeded_at": moment.isoformat(),
        "expectations": {
            "events": GROUND_TRUTH,
            "silence": EXPECTED_SILENCE,
        },
    }


__all__ = [
    "GROUND_TRUTH",
    "EXPECTED_BYPRODUCTS",
    "EXPECTED_SILENCE",
    "build_rows",
    "seed",
]
