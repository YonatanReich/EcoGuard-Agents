"""Demo B: eight concurrent events that exercise identity and routing.

The scenario follows Demo A's contract: it stores only observations in the
same shapes as the real collectors.  The ordinary detection, coordination,
analysis, planning, allocation and projection pipeline must turn them into
events.

The first four authored events concentrate on merge and separation boundaries.
The next four add a distant concurrent earthquake, an air-pollution advisory,
an uncorroborated text report, and a text report that should join a satellite
fire. A small amount of structured noise pins the corresponding suppression
boundaries.
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
EILAT_QUAKE = (29.5577, 34.9519)
NEGEV_STATION = (30.9644, 34.7008)
ASHDOD = (31.8014, 34.6435)
NETANYA = (32.3215, 34.8532)

# The first two cells touch, so their fire signals must be folded into B1.
# Beit Shemesh is several columns away: close enough to challenge a naive
# radius matcher, but outside the coordinator's one-cell identity boundary.
JERUSALEM_HILLS_CELL = "risk-05000m-r0052-c0017"
JERUSALEM_HILLS_SPREAD_CELL = "risk-05000m-r0053-c0017"
BEIT_SHEMESH_CELL = "risk-05000m-r0051-c0014"
ASHALIM_CELL = "risk-05000m-r0036-c0021"
TIBERIAS_CELL = "risk-05000m-r0074-c0024"
TIBERIAS_AFTERSHOCK_CELL = "risk-05000m-r0075-c0024"
EILAT_QUAKE_CELL = "risk-05000m-r0003-c0014"
NEGEV_STATION_CELL = "risk-05000m-r0034-c0009"
NETANYA_CELL = "risk-05000m-r0064-c0012"

# Real configured sources, so the text classifier's joins resolve against
# public reference data while all mutable demo rows stay inside demo_b.
FIRE_CHANNEL = (-1001411503185, "fireisrael7777", "כבאות והצלה ארצי")
POLICE_CHANNEL = (-1002843129862, "Israel_Police_100", "דוברות משטרת ישראל")
MDA_CHANNEL = (-1001177174722, "mdaisrael", "מגן דוד אדום")


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
    {
        "id": "B5",
        "event": (
            "A second earthquake near Eilat occurs during the Sea of Galilee "
            "aftershock sequence."
        ),
        "hazard": "earthquake",
        "latitude": EILAT_QUAKE[0],
        "longitude": EILAT_QUAKE[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 4.0,
        "expect_min_signals": 1,
        "expect_allocation": True,
        "expect_allocated_units": ["police"],
        "expect_routing": True,
        "expect_notes": (
            "The magnitude 4.8 Eilat event overlaps B4 in time but is hundreds "
            "of kilometres away. It must open a separate incident. With Claude "
            "unavailable, deterministic earthquake risk still permits the "
            "one-police-station fallback."
        ),
    },
    {
        "id": "B6",
        "event": (
            "A gradually worsening PM10 episode reaches an anomalous level at "
            "the Negev monitoring station."
        ),
        "hazard": "air_pollution",
        "latitude": NEGEV_STATION[0],
        "longitude": NEGEV_STATION[1],
        "expect_detected": True,
        "expect_route": "non_emergency",
        "expect_marker_within_km": 3.0,
        "expect_min_signals": 1,
        "expect_allocated_units": [],
        "expect_notes": (
            "Three ordinary readings lead into PM10 185 ug/m3, above this "
            "station's September baseline. Wind context is present for the "
            "downwind corridor. It belongs only in Advisory and must receive "
            "no resource allocation."
        ),
    },
    {
        "id": "B7",
        "event": (
            "One unverified Ashdod fire claim is repeated by three channels "
            "from the same forwarded origin."
        ),
        "hazard": "fire",
        "latitude": ASHDOD[0],
        "longitude": ASHDOD[1],
        "expect_detected": True,
        "expect_route": "uncorroborated",
        "expect_marker_within_km": 6.0,
        "expect_min_signals": 1,
        "expect_allocated_units": [],
        "requires_model_classification": True,
        "expect_notes": (
            "All three messages carry the same origin peer and message id, so "
            "they count as one source and must not promote the claim to an "
            "emergency. It is an Advisory with no risk or allocation. This "
            "event requires the model classifier because the keyword fallback "
            "deliberately does not extract a location."
        ),
    },
    {
        "id": "B8",
        "event": (
            "A Netanya fire report and a satellite hotspot describe the same "
            "event in one detection wave."
        ),
        "hazard": "fire",
        "latitude": NETANYA[0],
        "longitude": NETANYA[1],
        "expect_detected": True,
        "expect_route": "emergency",
        "expect_marker_within_km": 4.0,
        "expect_min_signals": 2,
        "requires_model_classification": True,
        "expect_notes": (
            "The text claim and FIRMS evidence must merge into one confirmed "
            "fire rather than an emergency plus an uncorroborated duplicate. "
            "With Claude unavailable, FIRMS still creates the fire but the "
            "keyword-only text candidate has no location and cannot join it; "
            "fire risk also remains unavailable, so no allocation is expected."
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


def _pollution(
    station: str,
    channel: str,
    pollutant: str,
    value: float,
    lat: float,
    lon: float,
    observed: datetime,
) -> dict[str, Any]:
    """One Ministry reading, including its provider-clock identity."""
    israel = observed.astimezone(timezone(timedelta(hours=2)))
    return {
        "unit": "µg/m³",
        "valid": True,
        "value": value,
        "location": {"latitude": lat, "longitude": lon},
        "provider": "israel_ministry_environment_air_monitoring",
        "pollutant": pollutant,
        "source_id": f"station:{station}",
        "observed_at": observed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "unit_source": "reading",
        "collected_at": observed.isoformat(),
        "reading_unit": "µg/m³",
        "metadata_unit": "µg/m³",
        "provider_unit": "µg/m³",
        "quality_policy": "ecoguard-provider-valid-signed-v1",
        "provider_status": "_",
        "quality_control": "preliminary_unvalidated",
        "measurement_unit": "µg/m³",
        "collection_status": "complete",
        "provider_status_id": "1",
        "provider_timestamp": israel.strftime("%Y-%m-%dT%H:%M:%S+02:00"),
        "provider_channel_id": channel,
        "provider_station_id": station,
        "provider_pollutant_id": "1",
    }


def _telegram(
    peer: int,
    message_id: int,
    channel: str,
    title: str,
    body: str,
    observed: datetime,
    *,
    forwarded: dict[str, int] | None = None,
) -> dict[str, Any]:
    """One Telegram message, in the exact shape the collector stores."""
    return {
        "kind": "telegram",
        "peer_id": peer,
        "raw_text": body,
        "edited_at": None,
        "posted_at": observed.isoformat(),
        "source_id": f"telegram:{peer}",
        "message_id": message_id,
        "source_url": f"https://t.me/{channel}/{message_id}",
        "channel_title": title,
        "channel_username": channel,
        "configured_username": channel,
        "source_verification": {
            "role": "unofficial",
            "tier": "unofficial",
            "event_verified": False,
            "peer_id_pinned": True,
            "peer_id_verified": True,
        },
        "forwarded_provenance": forwarded,
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

    def ago_5(minutes: int) -> datetime:
        """Snap Ministry readings to their real five-minute cadence."""
        moment = ago(minutes)
        return moment.replace(
            minute=moment.minute // 5 * 5,
            second=0,
            microsecond=0,
        )

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

    # --- B5: a concurrent earthquake far from the B4 sequence ------------
    observed = ago(52)
    rows.append(
        (
            "gsi_earthquake",
            EILAT_QUAKE_CELL,
            observed,
            _earthquake(
                "demo-b-gsi-eilat",
                observed,
                *EILAT_QUAKE,
                4.8,
                13.0,
                "Eilat Region",
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

    # --- B6: PM10 rises gradually before crossing the local baseline ------
    pm10_cell = "ministry:417:1:PM10:%C2%B5g%2Fm%C2%B3"
    for minutes, value in ((155, 24.0), (110, 32.0), (65, 58.0), (10, 185.0)):
        observed = ago_5(minutes)
        rows.append(
            (
                "air_pollution",
                pm10_cell,
                observed,
                _pollution(
                    "417",
                    "1",
                    "PM10",
                    value,
                    *NEGEV_STATION,
                    observed,
                ),
            )
        )
    rows.append(
        (
            "weather",
            NEGEV_STATION_CELL,
            ago(40),
            _weather(29.0, 35.0, 18.0, 24.0, 270.0),
        )
    )

    # --- B7: three copies, one forwarded origin, no independent source ----
    forwarded_origin = {
        "origin_peer_id": -1009000000001,
        "origin_message_id": 7001,
    }
    for channel_info, message_id, minutes in (
        (FIRE_CHANNEL, 991101, 34),
        (POLICE_CHANNEL, 591101, 29),
        (MDA_CHANNEL, 291101, 25),
    ):
        peer, channel, title = channel_info
        observed = ago(minutes)
        rows.append(
            (
                "telegram",
                f"telegram:{peer}:{message_id}",
                observed,
                _telegram(
                    peer,
                    message_id,
                    channel,
                    title,
                    "דיווח על שריפה במחסן באזור התעשייה באשדוד",
                    observed,
                    forwarded=forwarded_origin,
                ),
            )
        )

    # --- B8: one text claim corroborated by satellite evidence ------------
    rows.extend(
        [
            (
                "firms",
                NETANYA_CELL,
                ago(47),
                _firms(*NETANYA, 42.0, 1, satellite="SNPP"),
            ),
            (
                "firms",
                NETANYA_CELL,
                ago(13),
                _firms(*NETANYA, 105.0, 3, satellite="SNPP"),
            ),
            (
                "weather",
                NETANYA_CELL,
                ago(35),
                _weather(34.0, 24.0, 13.0, 28.0, 285.0),
            ),
        ]
    )
    peer, channel, title = POLICE_CHANNEL
    observed = ago(18)
    rows.append(
        (
            "telegram",
            f"telegram:{peer}:591180",
            observed,
            _telegram(
                peer,
                591180,
                channel,
                title,
                "שריפה פעילה סמוך לאזור התעשייה בנתניה, עשן נראה למרחוק",
                observed,
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
