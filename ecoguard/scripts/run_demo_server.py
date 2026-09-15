"""
Development server with stubbed fire detection.

The dashboard is empty by default, and that is correct behaviour rather than a
bug: NASA FIRMS only returns hotspots where fires actually are, so a typical
coordinate in Israel has nothing to show. Without a NASA_FIRMS_API_KEY it is
emptier still, because detection cannot run at all.

That makes the UI hard to develop against. This script runs the real app with
`fire_detection_agent` replaced by a stub that always returns one plausible
detected fire near Givat Shmuel, so the event cards, risk badges, protocol
citations and map markers all have something to render.

Nothing in the application is modified. This swaps a module global at startup,
the same way tests/test_events_api.py does, and it lives in scripts/ so it can
never be imported by the running service.

Risk analysis and response planning are NOT stubbed. With ANTHROPIC_API_KEY set
you get real, protocol-grounded reasoning over the stub event. Without it, both
agents report "missing credentials" and the dashboard shows the unassessed
state — grey marker, "not assessed" badge — which is itself worth looking at.

Usage:
    python scripts/run_demo_server.py            # port 8000
    python scripts/run_demo_server.py --port 8010

Then run the frontend as usual (`cd frontend && npm run dev`) and open the
dashboard. Do not use this for anything but local development.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from backend import main

# A realistic Shape A detected event: high-confidence satellite hotspot, very
# high fire weather, strong wind, a town and a hospital nearby and no fire
# station, which is the combination that exercises most of the UI.
STUB_EVENT = {
    "metadata": {"timestamp": "2026-08-28T11:00:00Z", "collection_status": "success"},
    "event_type": "fire",
    "detected": True,
    "location": {"latitude": 32.0786, "longitude": 34.8483},
    "detection_confidence": "high",
    "fire_weather_severity": "very_high",
    "satellite_evidence": {
        "source": "NASA FIRMS",
        "hotspots_count": 4,
        "selected_hotspot": {
            "latitude": 32.0786,
            "longitude": 34.8483,
            "acquisition_date": "2026-08-28",
            "acquisition_time": "1042",
            "satellite": "N20",
            "instrument": "VIIRS",
            "confidence": "h",
            "normalized_confidence": "high",
            "frp": 94.6,
            "daynight": "D",
        },
        "hotspots": [],
    },
    "fire_danger": {
        "source": "GWIS/EFFIS",
        "index": "FWI",
        "danger_level": "very_high",
        "fwi_min": 38.0,
        "fwi_max": 50.0,
    },
    "weather_context": {
        "current": {
            "temperature_c": 38.2,
            "humidity_percent": 14,
            "wind_speed_kmh": 41.0,
            "precipitation_mm": 0.0,
            "weather_code": 0,
        },
        "forecast": {"daily": {}},
    },
    "geospatial_context": {
        "terrain_type": None,
        "region_type": None,
        "vegetation_density": None,
        "distance_to_water_m": None,
        "nearby_roads": [{"name": "Route 4", "type": "trunk"}],
        "nearby_settlements": [{"name": "Givat Shmuel", "type": "town"}],
        "nearby_hospitals": [{"name": "Beilinson Hospital", "type": "hospital"}],
        "nearby_police_stations": [],
        "nearby_fire_stations": [],
        "nearby_green_areas": [],
        "nearby_water_sources": [],
    },
    "source_status": {
        "nasa_firms": "success",
        "gwis_effis": "success",
        "weather": "success",
        "geospatial": "partial",
    },
}


class StubFireDetectionAgent:
    """Stands in for FireDetectionAgent, always reporting one detected fire."""

    def detect_fire(self, **kwargs) -> dict:
        """
        Return the stub event, moved to whatever coordinate was requested.

        Honouring the requested coordinate means panning the map and rescanning
        behaves sensibly instead of always pinning the marker to Givat Shmuel.
        """
        event = {**STUB_EVENT}

        latitude = kwargs.get("latitude")
        longitude = kwargs.get("longitude")

        if latitude is not None and longitude is not None:
            event["location"] = {"latitude": latitude, "longitude": longitude}
            event["satellite_evidence"] = {
                **STUB_EVENT["satellite_evidence"],
                "selected_hotspot": {
                    **STUB_EVENT["satellite_evidence"]["selected_hotspot"],
                    "latitude": latitude,
                    "longitude": longitude,
                },
            }

        return event


def main_cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    main.fire_detection_agent = StubFireDetectionAgent()

    analysis_live = main.risk_agent.llm_service.available

    print("=" * 68)
    print("  DEMO SERVER — fire detection is STUBBED, not real")
    print("=" * 68)
    print("  Detection      : stubbed, always returns one fire")
    print(
        "  Risk + planning: "
        + ("LIVE Claude calls (slow, ~20-40s per request)" if analysis_live
           else "DISABLED — no ANTHROPIC_API_KEY, events show as unassessed")
    )
    print(
        f"  Protocols      : {len(main.protocol_retriever.chunks)} chunks from "
        f"{len(main.protocol_retriever.documents)} documents"
    )
    print(f"  Listening on   : http://{args.host}:{args.port}")
    print("=" * 68)

    uvicorn.run(main.app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
