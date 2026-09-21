"""Seed the demo database with fabricated incidents.

Run with:
    python -m ecoguard.scripts.seed_demo

Everything written here is invented — the risk scores, the plans, the incident
reports, the dispatch grades. The point is to show the dashboard, the response
plans and the resource allocator working on a full incident, which the live
feed only does when something is genuinely burning or flooding.

Two things are *not* invented, because a demo that dispatches from nowhere to
nowhere shows the allocator doing the one thing it does not do:

  * the responding stations are the real nearest ones, read out of the live
    reference tables (read-only; nothing is written to the live database);
  * the routes are real Mapbox driving routes between those stations and the
    incident, fetched once here and baked into the payload.

Both degrade rather than fail: with no live database the stations fall back to
a fixed list, and with no Mapbox token the route falls back to a straight line.
A demo that will not seed is worse than one that drives over a field.

The payloads are validated against the same SharedEvent contract the live feed
uses before anything is written, so a demo incident can never be a shape the
dashboard cannot render.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from pydantic import TypeAdapter
from sqlalchemy import create_engine, text

from ecoguard.shared.events import SharedEvent

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("seed_demo")

_event_adapter = TypeAdapter(SharedEvent)

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


# ---------------------------------------------------------------------------
# Real stations and real routes
# ---------------------------------------------------------------------------

# Used when the live reference database is unreachable, so the demo still
# seeds on a laptop with no DATABASE_URL. Coordinates are the published
# station locations; the names are transliterated rather than Hebrew because
# this branch is a fallback, not the intended source.
FALLBACK_STATIONS: dict[str, list[dict[str, Any]]] = {
    "fire_department": [
        {"database_id": 9001, "name": "Haifa Fire Station", "address": "Haifa",
         "latitude": 32.8156, "longitude": 34.9892},
        {"database_id": 9002, "name": "Tel Aviv Fire Station", "address": "Tel Aviv",
         "latitude": 32.0714, "longitude": 34.7818},
        {"database_id": 9003, "name": "Tiberias Fire Station", "address": "Tiberias",
         "latitude": 32.7922, "longitude": 35.5312},
    ],
    "police": [
        {"database_id": 9101, "name": "Haifa Police Station", "address": "Haifa",
         "latitude": 32.8184, "longitude": 34.9964},
        {"database_id": 9102, "name": "Tel Aviv Police Station", "address": "Tel Aviv",
         "latitude": 32.0669, "longitude": 34.7847},
        {"database_id": 9103, "name": "Tiberias Police Station", "address": "Tiberias",
         "latitude": 32.7889, "longitude": 35.5340},
    ],
    "medical_services": [
        {"database_id": 9201, "name": "MDA Haifa", "address": "Haifa",
         "latitude": 32.8092, "longitude": 34.9906},
        {"database_id": 9202, "name": "MDA Tel Aviv", "address": "Tel Aviv",
         "latitude": 32.0790, "longitude": 34.7900},
        {"database_id": 9203, "name": "MDA Tiberias", "address": "Tiberias",
         "latitude": 32.7950, "longitude": 35.5290},
    ],
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _load_reference_stations() -> dict[str, list[dict[str, Any]]]:
    """Read the live station tables, or fall back to the fixed list."""

    loaders = {
        "fire_department":
            "ecoguard.database.repositories.fire_stations:fire_stations_geojson",
        "police":
            "ecoguard.database.repositories.police_stations:police_stations_geojson",
        "medical_services":
            "ecoguard.database.repositories.mda_stations:mda_stations_geojson",
    }
    stations: dict[str, list[dict[str, Any]]] = {}
    for unit, target in loaders.items():
        module_name, function_name = target.split(":")
        try:
            module = __import__(module_name, fromlist=[function_name])
            collection = getattr(module, function_name)()
            stations[unit] = [
                {
                    "database_id": feature["properties"]["database_id"],
                    "name": feature["properties"].get("name") or f"Station {unit}",
                    "address": feature["properties"].get("address"),
                    "longitude": feature["geometry"]["coordinates"][0],
                    "latitude": feature["geometry"]["coordinates"][1],
                }
                for feature in collection["features"]
                if feature["properties"].get("database_id")
            ]
            log.info("%s: %d real stations", unit, len(stations[unit]))
        except Exception as error:  # noqa: BLE001 — any failure means fall back
            log.warning("%s: using fallback stations (%s)", unit, error)
            stations[unit] = FALLBACK_STATIONS[unit]
    return stations


def _nearest(
    stations: list[dict[str, Any]], latitude: float, longitude: float, count: int
) -> list[dict[str, Any]]:
    ranked = sorted(
        stations,
        key=lambda station: _haversine_km(
            latitude, longitude, station["latitude"], station["longitude"]
        ),
    )
    return ranked[:count]


def _mapbox_token() -> str | None:
    """The frontend's public token, which is what this repository actually has.

    A pk token is allowed to call Directions and is already in the bundle, so
    reading it here leaks nothing that is not public. MAPBOX_ACCESS_TOKEN wins
    when it is set, for anyone who has a backend token.
    """
    token = os.getenv("MAPBOX_ACCESS_TOKEN")
    if token:
        return token
    env_file = Path(__file__).resolve().parents[1] / "frontend" / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "VITE_MAPBOX_KEY":
            return value.strip() or None
    return None


def _straight_route(
    origin: tuple[float, float], destination: tuple[float, float]
) -> tuple[list[list[float]], float, float]:
    """Ten interpolated points, and a distance/duration at 50 km/h."""

    points = [
        [
            origin[0] + (destination[0] - origin[0]) * step / 10,
            origin[1] + (destination[1] - origin[1]) * step / 10,
        ]
        for step in range(11)
    ]
    distance_m = _haversine_km(origin[1], origin[0], destination[1], destination[0]) * 1000
    return points, distance_m, distance_m / (50_000 / 3600)


def _route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    token: str | None,
) -> dict[str, Any]:
    """One driving route, real when Mapbox answers and straight when it does not."""

    coordinates, distance_m, duration_s, provider = (
        *_straight_route(origin, destination),
        "straight_line_fallback",
    )
    if token:
        try:
            response = requests.get(
                "https://api.mapbox.com/directions/v5/mapbox/driving"
                f"/{origin[0]},{origin[1]};{destination[0]},{destination[1]}",
                params={
                    "geometries": "geojson",
                    "overview": "full",
                    "access_token": token,
                },
                timeout=20,
            )
            response.raise_for_status()
            route = response.json()["routes"][0]
            coordinates = route["geometry"]["coordinates"]
            distance_m = float(route["distance"])
            duration_s = float(route["duration"])
            provider = "mapbox"
        except Exception as error:  # noqa: BLE001 — a demo route is not worth failing on
            log.warning("Mapbox route failed, using a straight line (%s)", error)

    return {
        "status": "routed",
        "provider": provider,
        "profile": "driving",
        "distance_m": round(distance_m, 1),
        "duration_s": round(duration_s, 1),
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "origin": {"longitude": origin[0], "latitude": origin[1]},
        "destination": {"longitude": destination[0], "latitude": destination[1]},
        "estimated_arrival_at": _iso(NOW + timedelta(seconds=round(duration_s))),
        "road_access_verified": provider == "mapbox",
        "requires_field_access_confirmation": provider != "mapbox",
        "offroad_segment": None,
        "steps_he": [],
        "error": None,
    }


def _allocated_stations(
    reference: dict[str, list[dict[str, Any]]],
    latitude: float,
    longitude: float,
    wanted: dict[str, int],
    token: str | None,
    actions: dict[str, list[dict[str, Any]]],
    reason: str,
) -> list[dict[str, Any]]:
    allocated = []
    for unit, count in wanted.items():
        for station in _nearest(reference[unit], latitude, longitude, count):
            allocated.append({
                "database_id": station["database_id"],
                "name": station["name"],
                "address": station["address"],
                "unit_type": unit,
                "recommended_unit": unit,
                "latitude": station["latitude"],
                "longitude": station["longitude"],
                "distance_km": round(
                    _haversine_km(
                        latitude, longitude, station["latitude"], station["longitude"]
                    ),
                    2,
                ),
                "allocation_status": "allocated",
                "selection_reason": reason,
                "response_actions": actions.get(unit, []),
                "route": _route(
                    (station["longitude"], station["latitude"]),
                    (longitude, latitude),
                    token,
                ),
            })
    return allocated


def _requirements(wanted: dict[str, int], assigned: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for unit, requested in wanted.items():
        got = sum(1 for station in assigned if station["recommended_unit"] == unit)
        result[unit] = {
            "requested": requested,
            "assigned": got,
            "shortfall": max(0, requested - got),
        }
    return result


def _action(action: str, unit: str, timeframe: str) -> dict[str, Any]:
    return {
        "action": action,
        "responsible_unit": unit,
        "timeframe": timeframe,
        "supporting_protocol_chunk_ids": [],
    }


def _circle(latitude: float, longitude: float, radius_km: float, points: int = 48):
    """A closed ring approximating a circle, for impact areas and spread rings."""

    degrees_lat = radius_km / 111.32
    degrees_lon = radius_km / (111.32 * math.cos(math.radians(latitude)))
    ring = [
        [
            round(longitude + degrees_lon * math.cos(2 * math.pi * index / points), 6),
            round(latitude + degrees_lat * math.sin(2 * math.pi * index / points), 6),
        ]
        for index in range(points)
    ]
    ring.append(ring[0])
    return [ring]


def _cone(latitude: float, longitude: float, heading_deg: float, length_km: float,
          half_angle_deg: float):
    """A wedge from the ignition point downwind, for the spread forecast."""

    ring = [[round(longitude, 6), round(latitude, 6)]]
    for offset in range(-int(half_angle_deg), int(half_angle_deg) + 1, 5):
        bearing = math.radians(heading_deg + offset)
        ring.append([
            round(longitude + (length_km / (111.32 * math.cos(math.radians(latitude))))
                  * math.sin(bearing), 6),
            round(latitude + (length_km / 111.32) * math.cos(bearing), 6),
        ])
    ring.append(ring[0])
    return [ring]


# ---------------------------------------------------------------------------
# The incidents
# ---------------------------------------------------------------------------

FIRE_REPORT = """INCIDENT REPORT — DEMO-FIRE-001
Carmel Forest, east of Nesher

SITUATION
A fire was detected at 11:42 local time on the eastern slope of the Carmel
ridge, 2.4 km south-east of Nesher. Satellite confirmation from two passes,
corroborated by three ground reports. Estimated burning area at detection:
approximately 31 hectares, spreading north-east on a 24 km/h south-westerly.

FIRE BEHAVIOUR
Head rate of spread measured at 18 m/min through Aleppo pine and dense
Mediterranean scrub with an estimated fuel load of 24 t/ha. Relative humidity
is 19%, ambient temperature 34C, and the slope ahead of the head runs at 22%
upslope, which is accelerating the run towards the ridge line. Spotting up to
400 m ahead of the front has been observed.

EXPOSURE
Nesher (population 23,700) sits 2.4 km downwind and is forecast to be reached
in 95 minutes at the current head rate. Ramat Yishai and the Nesher industrial
zone lie inside the possible-spread envelope. One fuel depot and one high
voltage transmission corridor are in the projected path.

ACTIONS TAKEN
Grade 3 dispatch declared at 11:48. Six fire teams from three stations
assigned, with police for road closure on Route 672 and MDA staged at the
Nesher community centre. Aerial support requested and pending.

OUTSTANDING
Aerial firefighting confirmation. Evacuation decision for the Nesher eastern
neighbourhoods rests with the local authority and has not yet been taken.

-- Fabricated for demonstration. No such incident occurred."""

FLOOD_REPORT = (
    "Nahal Ayalon is running at a severity 5 stage following 68 mm of rain in "
    "four hours over the eastern catchment. Two crossings on the Ayalon "
    "corridor are impassable and a third is at the shoulder. Closure teams "
    "have been dispatched to both confirmed crossings; the third is being "
    "monitored. Fabricated for demonstration."
)

EARTHQUAKE_PLAN = (
    "Magnitude 5.2 at 11 km depth in the Jordan Valley, 6 km north of "
    "Tiberias. Minimum response policy applies: search and rescue staging at "
    "the nearest fire station, medical triage point established by MDA, and "
    "police traffic control on the access routes into the impact area. "
    "Structural survey teams to sweep pre-1980 construction first. "
    "Fabricated for demonstration."
)


def build_events(
    reference: dict[str, list[dict[str, Any]]], token: str | None
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    # --- Fire: Carmel forest, east of Nesher -------------------------------
    fire_lat, fire_lon = 32.7430, 35.0530
    fire_wanted = {"fire_department": 3, "police": 2, "medical_services": 1}
    fire_actions = {
        "fire_department": [
            _action("Attack the north-east flank from Route 672", "fire_department",
                    "immediate"),
            _action("Hold the ridge line above the Nesher eastern neighbourhood",
                    "fire_department", "within_1_hour"),
        ],
        "police": [
            _action("Close Route 672 between the junction and the quarry", "police",
                    "immediate"),
        ],
        "medical_services": [
            _action("Stage at the Nesher community centre", "medical_services",
                    "immediate"),
        ],
    }
    fire_stations = _allocated_stations(
        reference, fire_lat, fire_lon, fire_wanted, token, fire_actions,
        "Nearest available station to the incident, by driving distance",
    )
    events.append({
        "id": "demo-fire-carmel-001",
        "type": "fire",
        "title": "Forest fire — Carmel ridge, east of Nesher",
        "description": (
            "Active fire spreading north-east through pine and scrub towards "
            "Nesher. Head rate 18 m/min, 95 minutes to the nearest built-up "
            "edge."
        ),
        "latitude": fire_lat,
        "longitude": fire_lon,
        "observed_at": _iso(NOW - timedelta(minutes=38)),
        "classification": "emergency",
        "analysis_status": "success",
        "planning_status": "success",
        "details": {
            "detection_confidence": "high",
            "fire_weather_severity": "extreme",
            "risk_score": 87.0,
            "risk_level": "critical",
            "confidence": "high",
            "primary_drivers": [
                "Relative humidity 19% with a 24 km/h south-westerly",
                "Upslope run of 22% ahead of the head",
                "Continuous Aleppo pine and scrub, estimated 24 t/ha",
                "Built-up edge 2.4 km downwind",
            ],
            "explanation": (
                "Every driver points the same way: dry, windy, steep and fuelled, "
                "with a town in the path."
            ),
            "assumptions": [
                "Wind holds its current direction for the next two hours",
                "No aerial suppression is on scene before the ridge line",
            ],
            "evidence_gaps": ["No ground-truth perimeter since the 11:42 pass"],
            "limitations": [
                "Spread forecast assumes constant wind and uniform fuel",
            ],
            "recommended_units": ["fire_department", "police", "medical_services"],
            "response_plan": [
                "Contain the north-east flank before it reaches the ridge",
                "Close Route 672 and hold it for the duration",
                "Stage medical at the Nesher community centre",
                "Prepare the eastern neighbourhoods for evacuation",
            ],
            "response_actions": [
                _action("Declare a grade 3 incident", "fire_department", "immediate"),
                _action("Request aerial firefighting support", "fire_department",
                        "immediate"),
                _action("Close Route 672", "police", "immediate"),
                _action("Warn the Nesher local authority", "police", "within_1_hour"),
                _action("Establish a casualty collection point", "medical_services",
                        "within_1_hour"),
                _action("Monitor the southern flank for a wind shift",
                        "fire_department", "ongoing"),
            ],
            "protocol_citations": [],
            "resource_allocation": {
                "status": "allocated",
                "routing_status": "routed",
                "requirements": _requirements(fire_wanted, fire_stations),
                "shortages": {},
                "stations": fire_stations,
                "errors": [],
                "settlement": {
                    "population": 23700,
                    "households": 8100,
                    "authority": "Nesher Municipality",
                    "authority_type": "municipality",
                    "authority_phone": "04-8298111",
                    "authority_address": "Derech HaShalom 23, Nesher",
                    "authority_website": None,
                    "area_km2": 12.9,
                },
            },
            "detection": {
                "verdict": "confirmed",
                "score": 92,
                "reasons": [
                    {"signal": "satellite", "detail": "Two VIIRS passes, 375 m, high confidence"},
                    {"signal": "ground_reports", "detail": "Three corroborating reports"},
                ],
            },
            "spread": {
                "likely": {
                    "type": "Polygon",
                    "coordinates": _cone(fire_lat, fire_lon, 45, 2.0, 20),
                },
                "possible": {
                    "type": "Polygon",
                    "coordinates": _cone(fire_lat, fire_lon, 45, 3.4, 45),
                },
                "heading_deg": 45.0,
                "heading_compass": "NE",
                "head_rate_m_per_min": 18.0,
                "head_distance_m": 2160.0,
                "horizon_minutes": 120.0,
            },
            "exposed_settlements": [
                {"name": "Nesher", "name_he": "נשר", "population": 23700,
                 "exposure": "likely", "arrival_minutes": 95.0, "distance_m": 2400.0,
                 "authority_phone": "04-8298111", "fire_district": "Haifa",
                 "police_station": "Haifa"},
                {"name": "Ramat Yishai", "name_he": "רמת ישי",
                 "population": 7400, "exposure": "possible", "arrival_minutes": 190.0,
                 "distance_m": 5100.0, "authority_phone": None,
                 "fire_district": "Haifa", "police_station": "Yokneam"},
            ],
            "sites_at_risk": [
                {"name": "Nesher industrial fuel depot", "kind": "fuel_storage",
                 "category": "hazard", "exposure": "possible", "distance_m": 2900.0},
                {"name": "161 kV transmission corridor", "kind": "power_line",
                 "category": "economic", "exposure": "likely", "distance_m": 1600.0},
                {"name": "Carmel ridge lookout", "kind": "visitor_site",
                 "category": "life_safety", "exposure": "likely", "distance_m": 1200.0},
            ],
            "evacuation": [
                {"name": "Nesher eastern neighbourhoods", "priority": "prepare",
                 "population": 4200,
                 "reason": "Forecast head arrival in 95 minutes on the current wind",
                 "arrival_minutes": 95.0, "authority": "Nesher Municipality",
                 "authority_phone": "04-8298111", "police_station": "Haifa"},
                {"name": "Carmel ridge lookout", "priority": "immediate",
                 "population": 60, "reason": "Inside the likely spread envelope",
                 "arrival_minutes": 25.0, "authority": "KKL-JNF",
                 "authority_phone": None, "police_station": "Haifa"},
            ],
            "people_in_spread": 27900,
            "population_at_risk": {"likely": 23760, "possible": 4140},
            "dispatch": {
                "grade": 3,
                "grade_reason": (
                    "Built-up area inside the two-hour spread envelope with a "
                    "critical fire weather index"
                ),
                "teams_required": 8,
                "teams_assigned": 6,
                "teams_shortfall": 2,
                "home_district": "Haifa",
                "stations": [
                    {"name": station["name"], "district": "Haifa", "teams": 2,
                     "role": "primary" if index == 0 else "support",
                     "request_type": "initial_dispatch"}
                    for index, station in enumerate(fire_stations)
                    if station["recommended_unit"] == "fire_department"
                ],
                "police": [{"station": "Haifa", "role": "road_closure"}],
                "mda": [{"station": "Nesher", "role": "staging"}],
                "is_national_event": False,
                "national_event_basis": None,
                "limits": ["Aerial support requested but not confirmed"],
            },
            "incident_report": FIRE_REPORT,
            "coverage_gaps": ["No aerial confirmation of the perimeter"],
            "limits": [],
        },
    })

    # --- Flood: Nahal Ayalon, Tel Aviv -------------------------------------
    flood_lat, flood_lon = 32.0640, 34.8140
    flood_wanted = {"fire_department": 2, "police": 2, "medical_services": 1}
    flood_actions = {
        "fire_department": [
            _action("Water rescue standby at the Ayalon crossing", "fire_department",
                    "immediate"),
        ],
        "police": [
            _action("Close the southbound Ayalon ramp", "police", "immediate"),
        ],
        "medical_services": [
            _action("Stage at the Ayalon interchange", "medical_services",
                    "within_1_hour"),
        ],
    }
    flood_stations = _allocated_stations(
        reference, flood_lat, flood_lon, flood_wanted, token, flood_actions,
        "Nearest station with road access to the crossing",
    )
    events.append({
        "id": "demo-flood-ayalon-001",
        "type": "flood",
        "title": "Flooding — Nahal Ayalon, Tel Aviv",
        "description": (
            "Severity 5 stage on Nahal Ayalon after 68 mm in four hours. Two "
            "crossings impassable."
        ),
        "latitude": flood_lat,
        "longitude": flood_lon,
        "observed_at": _iso(NOW - timedelta(minutes=52)),
        "classification": "emergency",
        "analysis_status": "success",
        "planning_status": "success",
        "details": {
            "severity_level": 5,
            "return_period_label": "1 in 25 years",
            "risk_status": "success",
            "risk_score": 74,
            "risk_level": "high",
            "risk_confidence": "medium",
            "risk_primary_drivers": [
                "68 mm in four hours over the eastern catchment",
                "Saturated urban surface with no infiltration capacity",
                "Two crossings already over the deck",
            ],
            "risk_explanation": FLOOD_REPORT,
            "sources": [
                {
                    "station": {
                        "id": 4101,
                        "latitude": 32.0712,
                        "longitude": 34.8203,
                        "precision_m": 25.0,
                        "severity_level": 5,
                        "observed_at": _iso(NOW - timedelta(minutes=12)),
                        "stream_match": "matched",
                    },
                    "strategy": "matched_stream_reach",
                    "stream": {
                        "stream_id": 771,
                        "water_source_id": 331,
                        "name": "Nahal Ayalon",
                        "match_confidence": "high",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [34.8256, 32.0801], [34.8203, 32.0712],
                                [34.8161, 32.0664], [34.8140, 32.0640],
                                [34.8107, 32.0571], [34.8072, 32.0489],
                            ],
                        },
                    },
                }
            ],
            "response_sites": [
                {
                    "target_id": "demo-flood-site-1",
                    "source_station_id": 4101,
                    "severity_level": 5,
                    "strategy": "road_crossing_closure",
                    "road": {
                        "segment_id": 55021,
                        "source": "osm",
                        "source_feature_id": "way/1109221",
                        "road_class": "trunk",
                        "base_class": "highway",
                        "name": "Ayalon Highway",
                        "ref": "20",
                        "bridge": True,
                        "tunnel": False,
                        "vehicle_access": "closed",
                    },
                    "crossing_type": "bridge",
                    "urban": True,
                    "crossing_location": {"latitude": 32.0651, "longitude": 34.8152},
                    "allocation_location": {"latitude": 32.0649, "longitude": 34.8156},
                    "allocation_eligible": True,
                    "local_match_confidence": "high",
                    "mapbox_verification": {
                        "status": "verified", "verified": True, "reason": None,
                        "mapbox_snap_distance_m": 11.4,
                    },
                },
                {
                    "target_id": "demo-flood-site-2",
                    "source_station_id": 4101,
                    "severity_level": 4,
                    "strategy": "road_crossing_closure",
                    "road": {
                        "segment_id": 55088, "source": "osm",
                        "source_feature_id": "way/1109772", "road_class": "secondary",
                        "base_class": "highway", "name": "Derech Hashalom",
                        "ref": None, "bridge": False, "tunnel": True,
                        "vehicle_access": "restricted",
                    },
                    "crossing_type": "underpass",
                    "urban": True,
                    "crossing_location": {"latitude": 32.0593, "longitude": 34.8109},
                    "allocation_location": None,
                    "allocation_eligible": False,
                    "local_match_confidence": "medium",
                    "mapbox_verification": {
                        "status": "unverified", "verified": False,
                        "reason": "snap_distance_above_tolerance",
                        "mapbox_snap_distance_m": 143.0,
                    },
                },
            ],
            "allocation_ready_site_ids": ["demo-flood-site-1"],
            "targeting_status": "targets_selected",
            "targeting_reason": "One crossing verified against the road network",
            "allocation_target": {
                "target_id": "demo-flood-site-1",
                "latitude": 32.0651,
                "longitude": 34.8152,
            },
            "advisories": [
                {"type": "public", "action": "avoid",
                 "instruction": "Do not enter the Ayalon lanes or the underpasses.",
                 "scope": "Tel Aviv, Ayalon corridor"},
                {"type": "traffic", "action": "reroute",
                 "instruction": "Use Route 4 for north-south travel until reopening.",
                 "scope": "Gush Dan"},
            ],
            "response_actions": [
                _action("Close the Ayalon bridge crossing", "police", "immediate"),
                _action("Position water rescue at the crossing", "fire_department",
                        "immediate"),
                _action("Re-survey the underpass when the stage drops",
                        "fire_department", "within_6_hours"),
            ],
            "assumptions": ["Rainfall stops within the hour"],
            "evidence_gaps": ["No stage reading from the downstream gauge"],
            "resource_allocation": {
                "status": "allocated",
                "routing_status": "routed",
                "requirements": _requirements(flood_wanted, flood_stations),
                "shortages": {},
                "stations": flood_stations,
                "errors": [],
                "settlement": {
                    "population": 474530, "households": 210400,
                    "authority": "Tel Aviv-Yafo Municipality",
                    "authority_type": "city", "authority_phone": "03-7241111",
                    "authority_address": "Ibn Gabirol 69, Tel Aviv",
                    "authority_website": None, "area_km2": 52.0,
                },
            },
            "response_plan": {
                "summary": FLOOD_REPORT,
                "closures": ["Ayalon Highway southbound", "Derech Hashalom underpass"],
            },
            "change_type": "threshold_crossed",
            "threshold_transition": "4_to_5",
            "response_refresh_required": False,
            "existing_response_preserved": False,
            "limitations": [
                "Stream geometry is warning context, not confirmed inundation",
            ],
        },
    })

    # --- Earthquake: Jordan Valley, north of Tiberias ----------------------
    quake_lat, quake_lon = 32.8450, 35.5450
    quake_wanted = {"fire_department": 2, "police": 1, "medical_services": 2}
    quake_actions = {
        "fire_department": [
            _action("Establish search and rescue staging", "fire_department",
                    "immediate"),
        ],
        "police": [
            _action("Traffic control on Route 90", "police", "immediate"),
        ],
        "medical_services": [
            _action("Establish a triage point", "medical_services", "immediate"),
        ],
    }
    quake_stations = _allocated_stations(
        reference, quake_lat, quake_lon, quake_wanted, token, quake_actions,
        "Minimum response policy: nearest station per required unit",
    )
    events.append({
        "id": "demo-earthquake-tiberias-001",
        "type": "earthquake",
        "title": "Earthquake M5.2 — Jordan Valley, north of Tiberias",
        "description": (
            "Magnitude 5.2 at 11 km depth. Strong shaking expected across the "
            "Kinneret basin."
        ),
        "latitude": quake_lat,
        "longitude": quake_lon,
        "observed_at": _iso(NOW - timedelta(minutes=16)),
        "classification": "emergency",
        "analysis_status": "success",
        "planning_status": "success",
        "details": {
            "provider_event_id": "demo-gsi-2026-0921-01",
            "magnitude": 5.2,
            "depth_km": 11.0,
            "estimated_impact_radius_km": 18.0,
            "estimated_impact_area": {
                "type": "Polygon",
                "coordinates": _circle(quake_lat, quake_lon, 18.0),
            },
            "towns": [
                {"town_id": "demo-tiberias", "name_he": "טבריה",
                 "name_en": "Tiberias", "cbs_code": "2600"},
                {"town_id": "demo-migdal", "name_he": "מגדל",
                 "name_en": "Migdal", "cbs_code": "0072"},
                {"town_id": "demo-kinneret", "name_he": "כנרת",
                 "name_en": "Kinneret", "cbs_code": "0079"},
            ],
            "towns_status": "available",
            "population_summary": {
                "status": "available",
                "estimated_population": 61200,
                "intersected_cell_count": 148,
                "reason": None,
            },
            "source": "Geological Survey of Israel (fabricated demo record)",
            "plan_summary": EARTHQUAKE_PLAN,
            "recommended_units": ["fire_department", "medical_services", "police"],
            "response_actions": [
                _action("Search and rescue sweep of pre-1980 construction",
                        "fire_department", "immediate"),
                _action("Establish a triage point at the Tiberias promenade",
                        "medical_services", "immediate"),
                _action("Traffic control on Route 90", "police", "immediate"),
                _action("Survey bridges and the Kinneret shoreline road",
                        "fire_department", "within_6_hours"),
            ],
            "protocol_citations": [],
            "evidence_gaps": ["No felt reports aggregated yet"],
            "limitations": [
                "Impact radius is a magnitude-depth estimate, not a shaking model",
            ],
            "resource_allocation": {
                "status": "allocated",
                "routing_status": "routed",
                "requirements": _requirements(quake_wanted, quake_stations),
                "shortages": {},
                "stations": quake_stations,
                "errors": [],
                "settlement": {
                    "population": 49500, "households": 15200,
                    "authority": "Tiberias Municipality", "authority_type": "city",
                    "authority_phone": "04-6739111",
                    "authority_address": "HaYarden 1, Tiberias",
                    "authority_website": None, "area_km2": 10.9,
                },
                "unsupported_units": ["search_and_rescue_battalion"],
                "allocation_policy": "earthquake_minimum_response_v1",
                "allocation_basis": "protocol_recommended_units",
                "quantity_source": "ecoguard_minimum_response_policy",
            },
        },
    })

    # --- Air pollution advisory: Haifa Bay ---------------------------------
    events.append({
        "id": "demo-air-haifa-001",
        "type": "air_pollution",
        "title": "Elevated SO2 — Haifa Bay",
        "description": (
            "SO2 at the Haifa Bay station is running well above its seasonal "
            "baseline with a light onshore wind."
        ),
        "latitude": 32.8020,
        "longitude": 35.0510,
        "observed_at": _iso(NOW - timedelta(minutes=25)),
        "classification": "advisory",
        "analysis_status": "success",
        "planning_status": "success",
        "details": {
            "pollutant": "SO2",
            "station": {
                "id": "demo-haifa-bay",
                "name": "Haifa Bay (demo)",
                "provider": "demo",
                "channel_id": "demo-so2",
            },
            "measured_value": 214.0,
            "unit": "ppb",
            "observation_timestamp": _iso(NOW - timedelta(minutes=25)),
            "historical_baseline": {
                "p95": 78.0, "month": NOW.month, "hour": NOW.hour,
                "sample_count": 4180, "distinct_days": 340, "distinct_years": 4,
                "baseline_family": "demo", "baseline_version_id": "demo-1",
                "baseline_content_sha256": None,
            },
            "trend": "RISING",
            "recommendations": [
                {
                    "recommendation": "Advise sensitive groups to stay indoors",
                    "rationale": "Measured value is 2.7x the seasonal 95th percentile",
                    "responsible_authority_type": "municipality",
                    "resource_type": "public_communication",
                    "timeframe": "immediate",
                    "priority": "high",
                    "spatial_relevance": "Haifa Bay and the downwind neighbourhoods",
                },
                {
                    "recommendation": "Request an inspection of the bay industrial stacks",
                    "rationale": "The rise is confined to one station on an onshore wind",
                    "responsible_authority_type": "ministry_of_environmental_protection",
                    "resource_type": "inspection",
                    "timeframe": "within_6_hours",
                    "priority": "routine",
                    "spatial_relevance": "Haifa Bay industrial zone",
                },
            ],
            "limitations": ["Fabricated for demonstration; no Ministry index attached"],
        },
    })

    return events


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_events (
  id        text PRIMARY KEY,
  position  integer NOT NULL DEFAULT 0,
  payload   jsonb   NOT NULL
)
"""


def main() -> None:
    url = os.getenv("DEMO_DATABASE_URL")
    if not url:
        raise SystemExit("DEMO_DATABASE_URL is not set (see .env)")

    token = _mapbox_token()
    if not token:
        log.warning("No Mapbox token found; routes will be straight lines")

    events = build_events(_load_reference_stations(), token)

    # The check that matters: every payload must be a shape the live feed
    # could have produced, or the demo screen renders a blank card.
    for event in events:
        _event_adapter.validate_python(event)
    log.info("%d demo events validated against the SharedEvent contract", len(events))

    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text(SCHEMA))
        connection.execute(text("DELETE FROM demo_events"))
        for position, event in enumerate(events):
            connection.execute(
                text(
                    "INSERT INTO demo_events (id, position, payload) "
                    "VALUES (:id, :position, CAST(:payload AS jsonb))"
                ),
                {
                    "id": event["id"],
                    "position": position,
                    "payload": json.dumps(event),
                },
            )
    log.info("Seeded %d demo events", len(events))


if __name__ == "__main__":
    main()
