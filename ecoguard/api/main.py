"""
EcoGuard Agents — FastAPI application entry point.

Responsible for exposing the agent layer over HTTP and for combining the
output of several agents into the single unified response the frontend
dashboard consumes. This module owns transport concerns only — CORS, input
validation, status codes and error masking. All domain logic lives in the
agents package.

Endpoints:
    GET /                       Health check.
    GET /api/events             Durable shared event projections.
    GET /api/detected-events    Live fire detection, risk analysis and response
                                planning for one coordinate.
    GET /api/environmental-data Stored weather + live geospatial context for
                                one coordinate.
    POST /api/area-summary      Population, weather and fire danger aggregated
                                over a polygon drawn on the map.

Run locally with:
    uvicorn ecoguard.api.main:app --reload
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from ecoguard.detectors.fire.detection_agent import FireDetectionAgent
from ecoguard.analyzers.emergency.fire.risk_prediction_agent import FireRiskPredictionAgent
from ecoguard.shared.geospatial_context import GeospatialContextAgent
from ecoguard.response_planner.fire.planning_agent import ResponsePlanningAgent
from ecoguard.analyzers.emergency.fire.risk_analysis_agent import RiskAnalysisAgent, build_event_id
from ecoguard.shared.weather_reader import WeatherDataAgent
from ecoguard.api.area_schemas import AreaSummaryRequest, AreaSummaryResponse
from ecoguard.api.fire_risk_schemas import (
    FireRiskRequest,
    FireRiskResponse,
    NationalRiskScanResponse,
)
from ecoguard.shared.llm import ClaudeLLMService
from ecoguard.analyzers.emergency.fire.feature_builder import CurrentRiskFeatureBuilder
from ecoguard.analyzers.emergency.fire.refresh_orchestrator import CurrentRiskRefreshOrchestrator
from ecoguard.analyzers.emergency.fire.national_scan import NationalCurrentRiskScanService
from ecoguard.api.fire_danger_surface import build_surface as build_fire_danger_surface
from ecoguard.shared.protocols import ProtocolRetriever
from ecoguard.api.weak_events import router as weak_events_router
from ecoguard.api.demo import router as demo_router

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background workers, and make sure they stop with the app.

    The collection scheduler is imported here rather than at module scope so a
    developer without DATABASE_URL set still gets a working API for the old
    request-scoped endpoints; only collection is missing, and loudly.
    """

    current_risk_refresh.start()
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
        current_risk_refresh.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(events_router)
app.include_router(weak_events_router)
app.include_router(demo_router)

# Allow the Vite dev server to call the API directly during development.
# Both localhost and 127.0.0.1 are listed because browsers treat them as
# distinct origins. Port 5173 is Vite's default, 3000 covers a CRA-style setup.
# Note: in normal use the frontend goes through Vite's /api proxy
# (frontend/vite.config.ts) and is same-origin, so CORS is a fallback for
# calling the backend directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Agents are stateless and hold only configuration, so one shared instance
# each is enough for the whole process — no need to build them per request.
weather_agent = WeatherDataAgent()
geo_agent = GeospatialContextAgent()
fire_detection_agent = FireDetectionAgent()

# --- Fire risk prediction (ML) -------------------------------------------
# Estimates fire likelihood for a location from weather, terrain and land
# cover. This answers "where might a fire start", independently of whether
# any fire has been detected.
current_risk_feature_builder = CurrentRiskFeatureBuilder()
fire_risk_prediction_agent = FireRiskPredictionAgent()
national_risk_scan_service = NationalCurrentRiskScanService()
current_risk_refresh = CurrentRiskRefreshOrchestrator(scan_service=national_risk_scan_service)

# --- Risk analysis and response planning (LLM + RAG) ----------------------
# Interprets a *detected* fire event and plans a response, grounded in the
# protocol corpus. Distinct from the prediction model above: that one
# estimates likelihood, these two reason about an event that already exists.
#
# The protocol corpus is loaded and chunked once, here, and shared by both
# reasoning agents. Three markdown documents take a few milliseconds.
protocol_retriever = ProtocolRetriever()

# Two Claude clients rather than one: the planning call runs at lower effort
# because it works from an already-reasoned assessment, which keeps the second
# call from doubling the latency of the first.
risk_agent = RiskAnalysisAgent(
    llm_service=ClaudeLLMService(effort="medium"),
    retriever=protocol_retriever,
)
planning_agent = ResponsePlanningAgent(
    llm_service=ClaudeLLMService(effort="low"),
    retriever=protocol_retriever,
)

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
    from ecoguard.collection.fire.effis.collector import area_bounds
    from ecoguard.database.repositories.observations import latest_fire_danger_geojson

    now = time.monotonic()
    cached = _fire_danger_payload_cache.get("value")
    if cached is not None and now - _fire_danger_payload_cache["at"] < FIRE_DANGER_CACHE_SECONDS:
        return cached

    value = (latest_fire_danger_geojson(), area_bounds())
    _fire_danger_payload_cache["value"] = value
    _fire_danger_payload_cache["at"] = now
    return value


@app.get("/api/fire-danger")
def get_fire_danger():
    """Describe today's Fire Weather Index surface, without shipping it.

    Returns the geographic bounds and timestamp the frontend needs to place
    /api/fire-danger.png, rather than the 620 underlying points — the map
    renders the interpolated image, so the samples would be dead weight.

    Returns:
        dict: observed_at, bounds as [west, south, east, north], and the
            number of cells behind the surface. cell_count is 0 when the
            collector has not run yet.

    Raises:
        HTTPException: 503 when the observations store cannot be reached.
    """
    try:
        collection, bounds = _fire_danger_payload()
    except Exception as error:
        logging.error("Fire danger query failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Fire danger data is unavailable.")

    return {
        "observed_at": collection["observed_at"],
        "bounds": list(bounds),
        "cell_count": len(collection["features"]),
    }


@app.get("/api/fire-danger.png")
def get_fire_danger_surface():
    """Serve the Fire Weather Index as a smoothed, georeferenced RGBA PNG.

    The samples sit on a 5 km grid and Mapbox has no interpolating layer type,
    so every browser-side rendering of them — heatmap, circles, fill — draws
    one mark per sample and the grid shows through. Interpolating here produces
    a continuous surface, and a Gaussian-weighted average with a stated
    bandwidth is a method rather than a rendering accident.

    Transparent wherever no sample is near enough, so the Negev reads as the
    absence of data it is: Copernicus publishes no FWI over desert.

    Raises:
        HTTPException: 503 when the observations store cannot be reached, 404
            when no fire-weather observations exist yet.
    """
    try:
        collection, bounds = _fire_danger_payload()
    except Exception as error:
        logging.error("Fire danger query failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Fire danger data is unavailable.")

    if not collection["features"]:
        raise HTTPException(status_code=404, detail="No fire weather observations yet.")

    key = str(collection["observed_at"])
    png = _fire_danger_surface_cache.get(key)
    if png is None:
        png = build_fire_danger_surface(collection["features"], bounds)
        _fire_danger_surface_cache.clear()
        _fire_danger_surface_cache[key] = png

    return Response(
        content=png,
        media_type="image/png",
        # FWI is a daily product; an hour of browser caching costs nothing and
        # saves re-fetching 160 KB on every toggle of the layer.
        headers={"Cache-Control": "public, max-age=3600"},
    )


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

    from ecoguard.analyzers.non_emergency.water_level.advisory import (
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


@app.post("/api/area-summary", response_model=AreaSummaryResponse)
def get_area_summary(request: AreaSummaryRequest):
    """Summarise everything we store inside a polygon the user drew on the map.

    This replaced clicking a single coordinate. A point answers "what is the
    temperature here"; an operator's question is "how many people are inside
    this fire's likely path, and what is the weather doing across it", and only
    an area can answer that.

    Every figure comes from the store — the population grid, the hourly weather
    observations, today's Fire Weather Index and the station rosters — so this
    is one round trip with no upstream provider in the path, unlike the
    per-coordinate endpoints that wait on Open-Meteo and Overpass.

    Args:
        request: an AreaSummaryRequest carrying a GeoJSON Polygon. Its
            validator enforces Israel's bounding box, ring closure and a vertex
            ceiling; FastAPI turns a failure into a 422 naming the reason.

    Returns:
        AreaSummaryResponse: area in km², population, mean weather, mean and
            worst fire danger, and station counts. A section with no data
            underneath it reports nulls and cell_count 0 rather than vanishing.

    Raises:
        HTTPException: 503 when the store cannot be reached.
    """
    from ecoguard.database.repositories.area_summary import summarize_area

    try:
        return summarize_area(request.geometry)
    except Exception as error:
        logging.error("Area summary failed: %s", error, exc_info=True)
        raise HTTPException(status_code=503, detail="Area summary is unavailable.")


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


@app.post("/api/fire-risk", response_model=FireRiskResponse)
def assess_fire_risk(request: FireRiskRequest):
    """Return Current Risk without asserting that a fire was detected."""
    features = request.current_features
    build_result = None

    if features is None:
        build_result = current_risk_feature_builder.build(
            latitude=request.latitude,
            longitude=request.longitude,
        )
        if build_result.get("status") == "success":
            features = build_result.get("features")

    if features is None:
        reason = (
            build_result.get("reason")
            if build_result is not None
            else "complete_44_feature_payload_not_provided"
        )
        return {
            "status": "unavailable",
            "location": {"latitude": request.latitude, "longitude": request.longitude},
            "current_risk": {
                "status": "unavailable",
                "score": None,
                "level": None,
                "semantics": "estimated_fire_risk",
                "main_factors": [],
                "reason": reason,
                "missing_runtime_inputs": (
                    [] if build_result is not None else ["complete_44_feature_payload"]
                ),
                "model_version": None,
            },
            "actual_fire_detection": {
                "included": False,
                "semantics": "separate_firms_or_telegram_evidence",
            },
        }

    prediction = fire_risk_prediction_agent.predict(features)
    if prediction.get("status") != "ok":
        error = prediction.get("error") or {}
        return {
            "status": "error",
            "location": {"latitude": request.latitude, "longitude": request.longitude},
            "current_risk": {
                "status": "error",
                "score": None,
                "level": None,
                "semantics": "estimated_fire_risk",
                "main_factors": [],
                "reason": error.get("code", "prediction_failed"),
                "missing_runtime_inputs": error.get("missing_features", []),
                "model_version": None,
            },
            "actual_fire_detection": {
                "included": False,
                "semantics": "separate_firms_or_telegram_evidence",
            },
        }

    return {
        "status": "available",
        "location": {"latitude": request.latitude, "longitude": request.longitude},
        "current_risk": {
            "status": "available",
            "score": prediction["risk_score"],
            "level": prediction["risk_level"],
            "semantics": prediction["risk_semantics"],
            "main_factors": prediction.get("main_factors", []),
            "reason": None,
            "missing_runtime_inputs": [],
            "model_version": prediction.get("model_version"),
        },
        "actual_fire_detection": {
            "included": False,
            "semantics": "separate_firms_or_telegram_evidence",
        },
    }


@app.get("/api/fire-risk/national-scan", response_model=NationalRiskScanResponse)
def national_fire_risk_scan(evaluation_time: datetime | None = Query(default=None)):
    """Return the persisted latest scan; an explicit timestamp performs a deterministic local scan."""
    if evaluation_time is not None:
        return national_risk_scan_service.scan(evaluation_time)
    latest = current_risk_refresh.latest_snapshot()
    if latest is not None:
        return latest
    return current_risk_refresh.with_freshness(national_risk_scan_service.scan_and_save())


@app.get("/api/detected-events")
def get_detected_events(
    latitude: float = Query(
        default=31.783333,
        ge=ISRAEL_MIN_LATITUDE,
        le=ISRAEL_MAX_LATITUDE,
        description="Latitude must be within Israel's borders",
    ),
    longitude: float = Query(
        default=35.216667,
        ge=ISRAEL_MIN_LONGITUDE,
        le=ISRAEL_MAX_LONGITUDE,
        description="Longitude must be within Israel's borders",
    ),
    radius_km: float = Query(
        default=5.0,
        ge=1.0,
        le=50.0,
        description="How far from the requested point a hotspot counts as relevant",
    ),
    day_range: int = Query(
        default=2,
        ge=1,
        le=10,
        description="How many recent days of satellite data to inspect",
    ),
    include_analysis: bool = Query(
        default=True,
        description="Set false to skip risk analysis and response planning for a fast map render",
    ),
):
    """
    Detect fires near a coordinate, assess their risk, and plan a response.

    Runs the full pipeline: FireDetectionAgent (NASA FIRMS satellite hotspots,
    enriched with GWIS/EFFIS fire weather, Open-Meteo conditions and
    OpenStreetMap context), then RiskAnalysisAgent, then ResponsePlanningAgent.
    Both reasoning agents are grounded in the protocol corpus and cite it.

    Args:
        latitude (float): 29.45 to 33.35. Defaults to Jerusalem.
        longitude (float): 34.26 to 35.90. Defaults to Jerusalem.
        radius_km (float): Hotspot relevance radius from the requested point.
        day_range (int): Recent days of FIRMS data to inspect.
        include_analysis (bool): When false, detection runs but both model calls
            are skipped and the event is returned with analysis and planning
            marked "skipped".

    Returns:
        dict: metadata (including a per-service status breakdown), the query
            that produced it, and an events list holding zero or one event.

    Raises:
        HTTPException: 500 for an unexpected internal error, with the detail
            masked and the real exception logged. FastAPI returns 422 for
            out-of-bounds coordinates.

    Note this returns 200 with an empty events list when satellite detection
    fails, rather than 502. The dashboard fetches this on page load and its only
    failure handler logs to the console, so a 502 would blank the map with no
    user-visible explanation. /api/environmental-data does return 502 because it
    is user-initiated and has an error modal behind it.

    Performance: this is slow, typically 20-90 seconds. The OpenStreetMap
    Overpass lookup alone can take 30 seconds under load, and each of the two
    model calls adds several more. Pass include_analysis=false for a detection-
    only response. A background-job endpoint is the real fix and is not built.
    """
    logging.info(
        "Detected-events request for lat=%s, lon=%s, radius=%skm, days=%s, analysis=%s",
        latitude, longitude, radius_km, day_range, include_analysis,
    )

    try:
        event = fire_detection_agent.detect_fire(
            latitude=latitude,
            longitude=longitude,
            day_range=day_range,
            max_hotspot_distance_km=radius_km,
        )

        if include_analysis:
            risk = risk_agent.analyze_event(event)
            plan = planning_agent.plan_response(event, risk)
        else:
            # Detection only. Build the skipped shapes directly rather than
            # calling the agents, so no retrieval or model work happens at all.
            risk = risk_agent.build_skipped_assessment(event, "analysis_not_requested")
            plan = planning_agent.build_skipped_plan("analysis_not_requested", event)

        return build_detected_events_response(
            event=event,
            risk=risk,
            plan=plan,
            query={
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "day_range": day_range,
                "include_analysis": include_analysis,
            },
        )

    except HTTPException:
        raise

    except Exception as error:
        logging.error(
            "Unexpected internal error detecting events for lat=%s, lon=%s. Error: %s",
            latitude, longitude, str(error), exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Please try again later.",
        )


def build_event_title(event: dict) -> str:
    """
    Name the event after the nearest settlement, falling back to coordinates.

    Args:
        event (dict): A FireDetectionAgent result.

    Returns:
        str: A human-readable title for the dashboard.
    """
    geospatial = event.get("geospatial_context") or {}
    settlements = geospatial.get("nearby_settlements") or []

    for settlement in settlements:
        if isinstance(settlement, dict) and settlement.get("name"):
            return f"Fire detected near {settlement['name']}"

    location = event.get("location") or {}
    latitude = location.get("latitude")
    longitude = location.get("longitude")

    if latitude is None or longitude is None:
        return "Fire detected"

    return f"Fire detected at {latitude:.4f}, {longitude:.4f}"


def build_detected_events_response(*, event: dict, risk: dict, plan: dict, query: dict) -> dict:
    """
    Flatten the three agent results into the dashboard's event contract.

    The agents each return a nested, self-describing document; the frontend
    wants one flat object per marker. Doing that translation here keeps the
    transport shape out of the agents, which is what lets the agents stay
    testable without a notion of HTTP.

    Args:
        event (dict): FireDetectionAgent result.
        risk (dict): RiskAnalysisAgent result.
        plan (dict): ResponsePlanningAgent result.
        query (dict): The request parameters, echoed back.

    Returns:
        dict: The API response.
    """
    detection_status = (event.get("metadata") or {}).get("collection_status", "unknown")
    analysis_status = (risk.get("metadata") or {}).get("analysis_status", "skipped")
    planning_status = (plan.get("metadata") or {}).get("planning_status", "skipped")

    events = []

    # Only a positive detection produces a marker. detected False means the scan
    # ran and found nothing; detected None means it could not run at all. Neither
    # is an event, and inventing one for either would misreport the situation.
    if event.get("detected") is True:
        events.append(
            build_dashboard_event(event=event, risk=risk, plan=plan)
        )

    if detection_status == "failed":
        collection_status = "failed"
    elif "failed" in (analysis_status, planning_status):
        collection_status = "partial_service_failure"
    else:
        collection_status = "success"

    return {
        "metadata": {
            "timestamp": (event.get("metadata") or {}).get("timestamp"),
            "collection_status": collection_status,
            "services": {
                "detection": {"status": detection_status, "source": "NASA FIRMS"},
                "risk_analysis": {
                    "status": analysis_status,
                    "source": (risk.get("metadata") or {}).get("model"),
                },
                "response_planning": {
                    "status": planning_status,
                    "source": (plan.get("metadata") or {}).get("model"),
                },
                "protocols": {
                    "status": "success" if protocol_retriever.available else "failed",
                    "source": "local BM25 protocol corpus",
                },
            },
        },
        "query": query,
        "events": events,
    }


def build_dashboard_event(*, event: dict, risk: dict, plan: dict) -> dict:
    """
    Build one flat dashboard event from the three agent results.

    Args:
        event (dict): FireDetectionAgent result.
        risk (dict): RiskAnalysisAgent result.
        plan (dict): ResponsePlanningAgent result.

    Returns:
        dict: One event object for the dashboard's events list.
    """
    location = event.get("location") or {}
    actions = plan.get("response_actions") or []

    risk_citations = ((risk.get("grounding") or {}).get("citations")) or []
    plan_citations = ((plan.get("grounding") or {}).get("citations")) or []

    description = (
        plan.get("plan_summary")
        or risk.get("explanation")
        or "Fire detected. Risk analysis is not available for this event."
    )

    return {
        "id": build_event_id(event),
        "type": event.get("event_type", "fire"),
        "title": build_event_title(event),
        "description": description,
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),

        # Detection evidence, kept distinct from the risk judgement.
        "detection_confidence": event.get("detection_confidence"),
        "fire_weather_severity": event.get("fire_weather_severity"),

        # Risk analysis. All of these are None unless the analysis succeeded.
        "risk_score": risk.get("risk_score"),
        "risk_level": risk.get("risk_level"),
        "confidence": risk.get("confidence"),
        "primary_drivers": risk.get("primary_drivers") or [],
        "explanation": risk.get("explanation"),
        "evidence_gaps": risk.get("evidence_gaps") or [],
        "limitations": list(dict.fromkeys([
            *(risk.get("limitations") or []),
            *(plan.get("limitations") or []),
        ])),

        # Response plan. response_plan is the flattened form the dashboard
        # already expects; response_actions carries the unit and timeframe.
        "recommended_units": plan.get("recommended_units") or [],
        "response_plan": [action["action"] for action in actions],
        "response_actions": actions,
        "assumptions": plan.get("assumptions") or [],

        # Verified citations from both reasoning steps, merged.
        "protocol_citations": risk_citations + plan_citations,

        "analysis_status": (risk.get("metadata") or {}).get("analysis_status", "skipped"),
        "planning_status": (plan.get("metadata") or {}).get("planning_status", "skipped"),
    }

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
