"""The HTTP layer: every route the dashboard calls.

Owns transport only - cross-origin rules, request validation, status codes and
error masking. Every decision of substance is made further back, in the
detectors, analyzers and planners.

Run locally with `uvicorn ecoguard.api.main:app --reload`."""

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from ecoguard.shared.geospatial_context import GeospatialContextAgent
from ecoguard.shared.weather_reader import WeatherDataAgent
from ecoguard.api.area_schemas import AreaSummaryRequest, AreaSummaryResponse
from ecoguard.api.fire_danger_surface import build_surface as build_fire_danger_surface
from ecoguard.api.events import router as events_router
from ecoguard.api.scenario import router as scenario_router
from ecoguard.api.weak_events import router as weak_events_router
from ecoguard.api.demo import router as demo_router
from ecoguard.api.pipeline import router as pipeline_router

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background workers, and make sure they stop with the app.

    The collection scheduler is imported here rather than at module scope so a
    developer without DATABASE_URL set still gets a working API for the
    request-scoped environmental endpoint; only collection is missing, and
    loudly.
    """

    # Say in the boot log whether the model key works from this host; every
    # model-backed lane fails quietly otherwise. Never blocks startup.
    try:
        from ecoguard.shared.llm import probe_model_reachability

        probe_model_reachability()
    except Exception:
        logging.exception("Claude reachability probe itself failed")

    collection_scheduler = None
    try:
        from ecoguard.scheduler import scheduler as collection_scheduler

        collection_scheduler.start()
    except Exception:
        logging.exception("Collection scheduler did not start; no observations will be written")
    try:
        yield
    finally:
        if collection_scheduler is not None and collection_scheduler.running:
            collection_scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.include_router(events_router)
app.include_router(weak_events_router)
app.include_router(scenario_router)
app.include_router(demo_router)
app.include_router(pipeline_router)

# Allow the Vite dev server to call the API directly during development.
# Both localhost and 127.0.0.1 are listed because browsers treat them as
# distinct origins. Port 5173 is Vite's default, 3000 covers a CRA-style setup.
# Note: in normal use the frontend goes through Vite's /api proxy
# (frontend/vite.config.ts) and is same-origin, so CORS is a fallback for
# calling the backend directly.
#
# Testers reach the demo through a Pinggy tunnel, which gives the browser an
# https://<random>.pinggy.link origin. That subdomain changes every session, so
# it is matched by regex rather than listed. Requests still go through Vite's
# /api proxy and are same-origin in the normal case; this is the fallback for
# anyone calling the backend directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https://[a-z0-9-]+\.pinggy\.(link|io|online)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Agents are stateless and hold only configuration, so one shared instance
# each is enough for the whole process — no need to build them per request.
weather_agent = WeatherDataAgent()
geo_agent = GeospatialContextAgent()

# Israel's bounding box. Enforced on every coordinate parameter: it matches the
# product scope and stops the endpoints being used to scan arbitrary parts of
# the world through our upstream providers.
ISRAEL_MIN_LATITUDE = 29.45
ISRAEL_MAX_LATITUDE = 33.35
ISRAEL_MIN_LONGITUDE = 34.26
ISRAEL_MAX_LONGITUDE = 35.90


@app.get("/")
def read_root():
    """
    Health check.

    Returns:
        dict: A fixed message and status, used to confirm the server is up.
    """
    return {
        "message": "EcoGuard Agents API is running",
        "status": "success"
    }


# FWI is a daily product, so both the query and the ~500 ms numpy render are
# worth holding briefly. The TTL is what bounds staleness after the collector
# picks up a new day's raster; the surface itself is keyed on observed_at so a
# new day always replaces it.
FIRE_DANGER_CACHE_SECONDS = 600

_fire_danger_surface_cache: dict[str, bytes] = {}
_fire_danger_payload_cache: dict[str, Any] = {}


def _fire_danger_payload():
    """The fire-danger surface, recomputed only when the cached one has aged out."""
    from ecoguard.collectors.fire.effis.collector import area_bounds
    from ecoguard.database.repositories.observations import latest_fire_danger_geojson

    now = time.monotonic()
    cached = _fire_danger_payload_cache.get("value")
    if cached is not None and now - _fire_danger_payload_cache["at"] < FIRE_DANGER_CACHE_SECONDS:
        return cached

    value = (latest_fire_danger_geojson(), area_bounds())
    _fire_danger_payload_cache["value"] = value
    _fire_danger_payload_cache["at"] = now
    return value


@app.get("/api/fire-stations")
def get_fire_stations():
    """Serve the national fire station list as GeoJSON points.

    Reference data, not a live feed: it changes only when the Fire and Rescue
    Authority republishes its station list and the seed script is re-run. The
    query is 115 rows and costs a few milliseconds, so it is not cached — a
    cache here would mostly serve to hide a re-seed until the next restart.

    Returns:
        dict: A GeoJSON FeatureCollection, plus `located` and `total`. They
            differ because ten stations publish an address with no locality to
            geocode, and those carry no geometry to draw.

    Raises:
        HTTPException: 503 when the store cannot be reached.
    """
    from ecoguard.database.repositories.fire_stations import fire_stations_geojson

    try:
        return fire_stations_geojson()
    except Exception as error:
        logging.error("Fire station query failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Fire station data is unavailable.")


@app.get("/api/water-levels")
def get_water_levels():
    """Serve the current Kinneret advisory: level, trend, and what to do.

    Transport only. The bands, the trend and the recommended action are all
    computed by the advisory module against the Water Authority's published
    operating lines; nothing is decided here.

    Only the Kinneret is served. The Dead Sea has no published management
    thresholds and no inflow scheme, so there is no action to advise on and
    EcoGuard does not invent lines for it.

    Returns:
        dict: `status` "available" with an `advisory` object, or "unavailable"
            with a `reason` when nothing has been collected yet. A fresh
            database is the normal way to see the second one.

    Raises:
        HTTPException: 503 when the observation store cannot be reached.
    """
    from dataclasses import asdict

    from ecoguard.analyzers.water_level.advisory import (
        LevelReading,
        advise,
    )
    from ecoguard.database.repositories.observations import (
        read_kinneret_level_history,
    )

    try:
        rows = read_kinneret_level_history()
    except Exception as error:
        logging.error("Kinneret level query failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Water level data is unavailable.")

    readings = [
        LevelReading(
            observed_at=row["observed_at"],
            level_m=float(row["payload"]["level_m"]),
        )
        for row in rows
        if isinstance(row.get("payload"), dict)
        and row["payload"].get("level_m") is not None
    ]
    if not readings:
        return {
            "status": "unavailable",
            "reason": "no_kinneret_readings_collected_yet",
        }
    return {"status": "available", "advisory": asdict(advise(readings))}


@app.get("/api/police-stations")
def get_police_stations():
    """Serve the Israel Police station list as GeoJSON points.

    Reference data like /api/fire-stations, and the same shape, but every
    coordinate here is published rather than derived — there is no precision
    field because there is no approximation to qualify.

    Returns:
        dict: A GeoJSON FeatureCollection, plus `located` and `total`. They are
            always equal: police_stations.location is NOT NULL.

    Raises:
        HTTPException: 503 when the store cannot be reached.
    """
    from ecoguard.database.repositories.police_stations import police_stations_geojson

    try:
        return police_stations_geojson()
    except Exception as error:
        logging.error("Police station query failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Police station data is unavailable.")


@app.get("/api/system/actors")
def get_system_actors():
    """What every system actor is doing right now, for the System page.

    Read from process memory, so it is cheap enough to poll every second or
    two. An actor absent from `actors` has not run since this process started.

    Returns:
        dict: `actors` keyed by id, each with `live`, `runs`,
            `last_started_at`, `last_finished_at` and `last_outcome`;
            `pipeline` with whether the scheduler is running and when the next
            detection wave is due; and `server_time`, so the page measures
            "ran 3 minutes ago" on the server clock, not the browser one.
    """
    from datetime import datetime, timezone

    from ecoguard.shared.activity import snapshot

    pipeline = {"scheduler_running": False, "next_wave_at": None}
    try:
        from ecoguard.scheduler import scheduler

        job = scheduler.get_job("detect_and_coordinate")
        pipeline = {
            "scheduler_running": bool(scheduler.running),
            "next_wave_at": job.next_run_time.isoformat() if job and job.next_run_time else None,
        }
    except Exception:
        # No DATABASE_URL, or the scheduler failed to import: the page shows
        # the pipeline as stopped rather than the endpoint failing.
        logging.debug("scheduler state unavailable", exc_info=True)

    return {
        "actors": snapshot(),
        "pipeline": pipeline,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/responsible-parties")
def get_responsible_parties(
    latitude: float = Query(ge=29.0, le=33.6, description="Event latitude, WGS84."),
    longitude: float = Query(ge=34.0, le=36.0, description="Event longitude, WGS84."),
):
    """Who to call about a place: its authority, police, nearest fire and MDA.

    Feeds the event panel's "responsible" box for every hazard type, including
    those with no resource allocation of their own. The bounds are Israel's
    service area with a margin; anything outside it has no one on file.

    Returns:
        dict: `authority` (with phone), `police_station` (with phone and a
            `basis` of "responsible" or "nearest"), `nearest_fire_station` and
            `nearest_mda_station`, each with a straight-line `distance_m`.

    Raises:
        HTTPException: 503 when the store cannot be reached.
    """
    from ecoguard.database.repositories.responsible_services import responsible_parties_at

    try:
        return responsible_parties_at(latitude=latitude, longitude=longitude)
    except Exception as error:
        logging.error("Responsible-parties lookup failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Responsible-party data is unavailable.")


@app.get("/api/towns/search")
def search_towns_endpoint(
    q: str = Query(description="Part of a town name, in Hebrew or English."),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Find settlements by name, for the operator's search box.

    Deliberately geometry-free. The response carries the bounding box and a
    label point, which is everything the map needs to fly to the town and open
    a popup inside it; the outline itself is a second request, made once the
    operator has actually picked one.

    Args:
        q: any part of the Hebrew or English name.
        limit: how many matches to return, best first.

    Returns:
        dict: `{"towns": [...]}`, each with name, population, fire district,
            responsible police station, authority contact details, `bbox` and
            `label`.

    Raises:
        HTTPException: 503 when the store cannot be reached.
    """
    from ecoguard.database.repositories.towns import search_towns

    try:
        return {"towns": search_towns(q, limit=limit)}
    except Exception as error:
        logging.error("Town search failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Town data is unavailable.")


# Declared before /api/towns/{town_id}, which would otherwise take "outlines"
# for a town id.
@app.get("/api/towns/outlines")
def get_town_outlines(
    id: list[str] = Query(default=[], description="Town ids, repeatable."),
    name: list[str] = Query(default=[], description="Hebrew or English town names, repeatable."),
):
    """Outlines of the settlements an event touches, for the map's glow.

    Returns:
        dict: a GeoJSON FeatureCollection; each feature's properties carry
            `town_id`, `name_he` and `name_en` so the caller can match it back
            to whichever it asked by.

    Raises:
        HTTPException: 422 for more than 200 ids or names, 503 when the store
            cannot be reached.
    """
    if len(id) > 200 or len(name) > 200:
        raise HTTPException(status_code=422, detail="Ask for at most 200 towns at a time.")

    from ecoguard.database.repositories.towns import town_outlines

    try:
        return town_outlines(ids=id, names=name)
    except Exception as error:
        logging.error("Town outline lookup failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Town data is unavailable.")


@app.get("/api/towns/{town_id}")
def get_town(town_id: str):
    """One settlement as a GeoJSON Feature, outline included.

    Args:
        town_id: the id from a search result.

    Returns:
        dict: a GeoJSON Feature whose properties are the same town record the
            search endpoint returns.

    Raises:
        HTTPException: 404 when no such town, 503 when the store is unreachable.
    """
    from ecoguard.database.repositories.towns import town_outline

    try:
        feature = town_outline(town_id)
    except Exception as error:
        logging.error("Town lookup failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Town data is unavailable.")

    if feature is None:
        raise HTTPException(status_code=404, detail=f"No town {town_id!r}.")
    return feature


@app.get("/api/mda-stations")
def get_mda_stations():
    """Serve the Magen David Adom station roster as GeoJSON points.

    Same shape as /api/fire-stations, including `precision`: MDA publishes no
    coordinates, so a station is placed on its mapped building where OSM covers
    it and on its published address otherwise.

    Returns:
        dict: A GeoJSON FeatureCollection, plus `located` and `total`. They
            differ because part of the roster gives no address to resolve.

    Raises:
        HTTPException: 503 when the store cannot be reached.
    """
    from ecoguard.database.repositories.mda_stations import mda_stations_geojson

    try:
        return mda_stations_geojson()
    except Exception as error:
        logging.error("MDA station query failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="MDA station data is unavailable.")


@app.post("/api/dev/run/{source}")
def run_collector_now(source: str):
    """Run one collector immediately instead of waiting for its next tick.

    Off unless ECOGUARD_DEV_ENDPOINTS is set. Defined as a sync endpoint on
    purpose: FastAPI runs it in a worker thread, which the Telegram collector
    needs because it opens its own event loop.
    """
    if os.getenv("ECOGUARD_DEV_ENDPOINTS") != "1":
        raise HTTPException(status_code=404, detail="Not Found")

    from ecoguard.scheduler import COLLECTORS, run_once

    if source not in COLLECTORS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown collector. Known sources: {sorted(COLLECTORS)}",
        )

    # run() never raises, so the outcome is in collector_runs, not the response.
    run_once(source)
    return {"source": source, "status": "run complete; see collector_runs for the outcome"}


@app.get("/api/environmental-data")
def get_environmental_data(
    latitude: float = Query(
        default=31.783333,
        ge=ISRAEL_MIN_LATITUDE,
        le=ISRAEL_MAX_LATITUDE,
        description="Latitude must be within Israel's borders"
    ),
    longitude: float = Query(
        default=35.216667,
        ge=ISRAEL_MIN_LONGITUDE,
        le=ISRAEL_MAX_LONGITUDE,
        description="Longitude must be within Israel's borders"
    )):
    """
    Unify environmental data for a single coordinate.

    Merges two agents that no longer work the same way. The weather agent
    reads the collection layer's stored observations, answering from the 5 km
    grid cell containing the point — metadata.services.weather.observation
    names the cell and its distance. The geospatial agent still calls
    OpenStreetMap Overpass live, because nothing collects that on a timer.

    The coordinate bounds are enforced by FastAPI on the Query parameters
    above, which restrict input to Israel's bounding box — this matches the
    product scope and, for the one remaining live provider, stops the endpoint
    being used to scan arbitrary parts of the world through it.

    Because each agent reports its own collection_status instead of raising,
    one failing degrades the response rather than breaking it. Only a double
    failure is treated as an outage.

    Args:
        latitude (float): 29.45 to 33.35. Defaults to Jerusalem.
        longitude (float): 34.26 to 35.90. Defaults to Jerusalem.

    Returns:
        dict: Unified record with metadata (including a per-service status
            breakdown), location, geospatial_context, weather, summary
            counts and the list of geospatial layers that came back empty.

    Raises:
        HTTPException: 502 if both upstream providers failed, 500 for any
            unexpected internal error. The 500 detail is deliberately generic
            — the real exception is logged server-side rather than returned,
            so internal paths and stack traces are not leaked to clients.
            FastAPI itself returns 422 for out-of-bounds coordinates.

    Performance: dominated entirely by the geospatial agent's Overpass call,
    which takes seconds and occasionally 30+. The weather half used to add its
    own provider round trip and is now a single indexed read.
    """
    logging.info(f"Received environmental data request for lat={latitude}, lon={longitude}")

    try:
        weather_response = weather_agent.fetch_weather_data(latitude, longitude)
        geo_response = geo_agent.fetch_nearby_context(latitude, longitude, radius_km=2)

        weather_status = weather_response.get("metadata", {}).get("collection_status")
        geo_status = geo_response.get("metadata", {}).get("collection_status")

        # Both down means we have nothing useful to return, so surface it as
        # an upstream gateway error. One down still yields a usable response.
        if weather_status == "failed" and geo_status == "failed":
            collection_status = "failed"
            logging.error(f"Error fetching data from external APIs for lat={latitude}, lon={longitude}")
            raise HTTPException(
                status_code=502, 
                detail="Error fetching data."
            )
        elif weather_status == "failed" or geo_status == "failed":
            collection_status = "partial_service_failure" 
        else:
            collection_status = "success"


        # Merge the two agent results. Each agent returns the same top-level
        # shape but only fills the section it owns, so the merge is a matter
        # of picking the authoritative section from each: weather from the
        # weather agent, everything geospatial from the geospatial agent.
        unified_data = {
            "metadata": {
                "timestamp": weather_response.get("metadata", {}).get("timestamp"),
                
                "collection_status": collection_status,
                "services": {
                    "weather": {
                        "status": weather_status,
                        "source": weather_response.get("metadata", {}).get("data_source", "open-meteo")
                    },
                    "geospatial": {
                        "status": geo_status,
                        "source": geo_response.get("metadata", {}).get("data_source", "OpenStreetMap")
                    }
                }
            },
            "location": {
                "latitude": latitude,
                "longitude": longitude,
            },
            "geospatial_context": geo_response.get("geospatial_context", {}),
            "weather": weather_response.get("weather", {}),
            "summary": geo_response.get("summary", {}),
            "missing_layers": geo_response.get("missing_layers", [])
        }
        
        logging.info(f"Successfully processed and unified environmental data for lat={latitude}, lon={longitude}")
        return unified_data

    # Re-raise our own deliberate 502 untouched; without this it would be
    # swallowed by the generic handler below and reported as a 500.
    except HTTPException as http_err:
        raise http_err

    except Exception as e:
        logging.error(
            f"Unexpected internal error processing environmental data for lat={latitude}, lon={longitude}. Error: {str(e)}", 
            exc_info=True
        )
        raise HTTPException(
            status_code=500, 
            detail="Internal server error. Please try again later."
        )
