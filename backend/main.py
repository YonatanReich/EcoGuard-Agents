"""
EcoGuard Agents — FastAPI application entry point.

Responsible for exposing the agent layer over HTTP and for combining the
output of several agents into the single unified response the frontend
dashboard consumes. This module owns transport concerns only — CORS, input
validation, status codes and error masking. All domain logic lives in the
agents package.

Endpoints:
    GET /                       Health check.
    GET /api/detected-events    Fire pipeline output plus the latest stored
                                air-pollution event state.
    GET /api/environmental-data Live weather + geospatial context for one
                                coordinate.

Run locally with:
    uvicorn backend.main:app --reload
"""

import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from agents.fire_detection_agent import FireDetectionAgent
from agents.fire_risk_prediction_agent import FireRiskPredictionAgent
from agents.geospatial_context_agent import GeospatialContextAgent
from agents.response_planning_agent import ResponsePlanningAgent
from agents.risk_analysis_agent import RiskAnalysisAgent, build_event_id
from agents.weather_data_agent import WeatherDataAgent
from agents.resource_allocation_agent import ResourceAllocationAgent
from backend.fire_risk_schemas import (
    FireRiskRequest,
    FireRiskResponse,
    NationalRiskScanResponse,
)
from services.claude_llm_service import ClaudeLLMService
from services.current_risk_feature_builder import CurrentRiskFeatureBuilder
from services.current_risk_refresh_orchestrator import CurrentRiskRefreshOrchestrator
from services.national_current_risk_scan_service import NationalCurrentRiskScanService
from services.protocol_retrieval_service import ProtocolRetriever
from agents.coordinator import FireCoordinator
from backend.air_pollution_event_adapter import attach_air_pollution_state
from services.air_pollution_event_store import InMemoryAirPollutionEventStore
from services.air_pollution_runtime_service import AirPollutionRuntimeService
from services.air_pollution_transport_prediction_service import (
    AirPollutionTransportConfigurationError,
    configured_air_pollution_transport_prediction_service,
)
from services.ims_wind_observation_client import IMSWindObservationError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = FastAPI()

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

# Transitional runtime boundary for EA-313. The API reads this store only; the
# independently scheduled refresh performs Ministry collection, EA-309
# detection, and optional EA-310/311 context/support. It deliberately stops
# before Coordinator routing and EA-312 planning. Replace the in-memory store
# with the shared PostGIS repository without changing API/frontend callers.
air_pollution_event_store = InMemoryAirPollutionEventStore()
try:
    air_pollution_transport_service = (
        configured_air_pollution_transport_prediction_service()
    )
    air_pollution_transport_configuration_error = None
except AirPollutionTransportConfigurationError as error:
    air_pollution_transport_service = None
    air_pollution_transport_configuration_error = error.category
except IMSWindObservationError:
    air_pollution_transport_service = None
    air_pollution_transport_configuration_error = (
        "air_pollution_transport_ims_configuration_unavailable"
    )
air_pollution_runtime = AirPollutionRuntimeService(
    store=air_pollution_event_store,
    transport_service=air_pollution_transport_service,
    transport_configuration_error=air_pollution_transport_configuration_error,
)

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
allocation_agent = ResourceAllocationAgent()

# Israel's bounding box. Enforced on every coordinate parameter: it matches the
# product scope and stops the endpoints being used to scan arbitrary parts of
# the world through our upstream providers.
ISRAEL_MIN_LATITUDE = 29.45
ISRAEL_MAX_LATITUDE = 33.35
ISRAEL_MIN_LONGITUDE = 34.26
ISRAEL_MAX_LONGITUDE = 35.90


@app.on_event("startup")
def start_current_risk_refresh():
    current_risk_refresh.start()
    air_pollution_runtime.start()


@app.on_event("shutdown")
def stop_current_risk_refresh():
    air_pollution_runtime.stop()
    current_risk_refresh.stop()


fire_coordinator = FireCoordinator(
    detection_agent=fire_detection_agent,
    risk_agent=risk_agent,
    planning_agent=planning_agent,
    allocation_agent=allocation_agent,
)

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
    Detect fires near a coordinate and include stored air-pollution events.

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
            that produced the fire scan, and independent fire/pollution events.

    Raises:
        HTTPException: 500 for an unexpected internal error, with the detail
            masked and the real exception logged. FastAPI returns 422 for
            out-of-bounds coordinates.

    Note this returns 200 with an empty events list when satellite detection
    fails, rather than 502. The dashboard fetches this on page load and its only
    failure handler logs to the console, so a 502 would blank the map with no
    user-visible explanation. /api/environmental-data does return 502 because it
    is user-initiated and has an error modal behind it.

    Performance: the fire path is slow, typically 20-90 seconds. The OpenStreetMap
    Overpass lookup alone can take 30 seconds under load, and each of the two
    model calls adds several more. Pass include_analysis=false for a detection-
    only response. Air-pollution state is read from its refresh store and never
    invokes Ministry collection, geospatial lookup, or model work here.
    """
    logging.info(
        "Detected-events request for lat=%s, lon=%s, radius=%skm, days=%s, analysis=%s",
        latitude, longitude, radius_km, day_range, include_analysis,
    )

    try:
        pipeline = fire_coordinator.run_event_pipeline(
            latitude,
            longitude,
            day_range=day_range,
            radius_km=radius_km,
            include_analysis=include_analysis,
        )

        response = build_detected_events_response(
            pipeline=pipeline,
            query={
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "day_range": day_range,
                "include_analysis": include_analysis,
            },
        )
        response = attach_air_pollution_state(
            response,
            air_pollution_event_store.snapshot(),
        )
        return response

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


def build_detected_events_response(*, pipeline: dict, query: dict) -> dict:
    """
    Flatten the coordinator pipeline result into the dashboard's event contract.

    The agents each return a nested, self-describing document; the frontend
    wants one flat object per marker. Doing that translation here keeps the
    transport shape out of the agents, which is what lets the agents stay
    testable without a notion of HTTP.

    Args:
        pipeline (dict): FireCoordinator result.
        query (dict): The request parameters, echoed back.

    Returns:
        dict: The API response.
    """
    event = pipeline.get("detection") or {}
    risk = pipeline.get("risk_analysis") or {}
    plan = pipeline.get("planning") or {}

    detection_status = (event.get("metadata") or {}).get("collection_status", "unknown")
    analysis_status = (risk.get("metadata") or {}).get("analysis_status", "skipped")
    planning_status = (plan.get("metadata") or {}).get("planning_status", "skipped")
    allocation_status = (pipeline.get("allocated_resources") or {}).get("status", "skipped")

    events = []

    # Only a positive detection produces a marker. detected False means the scan
    # ran and found nothing; detected None means it could not run at all. Neither
    # is an event, and inventing one for either would misreport the situation.
    if event.get("detected") is True:
        events.append(build_dashboard_event(pipeline=pipeline))

    if detection_status == "failed" or pipeline.get("status") == "error":
        collection_status = "failed"
    elif pipeline.get("status") == "partial":
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
                "resource_allocation": {
                    "status": allocation_status,
                    "source": "OpenStreetMap geographic candidates",
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


def build_dashboard_event(*, pipeline: dict) -> dict:
    """
    Build one flat dashboard event from a coordinator pipeline result.

    Args:
        pipeline (dict): FireCoordinator result.

    Returns:
        dict: One event object for the dashboard's events list.
    """
    event = pipeline.get("detection") or {}
    risk = pipeline.get("risk_analysis") or {}
    plan = pipeline.get("planning") or {}
    location = pipeline.get("location") or event.get("location") or {}
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
        "detection_source": (event.get("metadata") or {}).get("source") or "NASA FIRMS",

        # Risk analysis. All of these are None unless the analysis succeeded.
        "risk_score": risk.get("risk_score"),
        "risk_level": risk.get("risk_level"),
        "confidence": risk.get("confidence"),
        "primary_drivers": risk.get("primary_drivers") or [],
        "explanation": risk.get("explanation"),
        "evidence_gaps": risk.get("evidence_gaps") or [],

        # Response plan. response_plan is the flattened form the dashboard
        # already expects; response_actions carries the unit and timeframe.
        "plan_summary": plan.get("plan_summary"),
        "assumptions": plan.get("assumptions") or [],
        "recommended_units": plan.get("recommended_units") or [],
        "response_plan": [action["action"] for action in actions],
        "response_actions": actions,
        "allocated_resources": pipeline.get("allocated_resources") or {},
        "nearby_roads": pipeline.get("nearby_roads") or [],

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
    Collect and unify live environmental data for a single coordinate.

    Calls the weather agent and the geospatial agent for the given point and
    merges their two results into one response. The coordinate bounds are
    enforced by FastAPI on the Query parameters above, which restrict input
    to Israel's bounding box — this both matches the product scope and stops
    the endpoint being used to scan arbitrary parts of the world through our
    upstream providers.

    Because each agent reports its own collection_status instead of raising,
    a failure in one provider degrades the response rather than breaking it.
    Only a double failure is treated as an outage.

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

    Performance: this typically takes several seconds, occasionally 30+.
    The geospatial agent's Overpass call dominates; the two agents also run
    sequentially here, so their latencies add.
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

@app.get("/api/analyze-location")
def analyze_location(
    latitude: float = Query(
        default=31.783333, 
        ge=29.45, 
        le=33.35, 
        description="Latitude must be within Israel's borders"
    ),
    longitude: float = Query(
        default=35.216667, 
        ge=34.26, 
        le=35.90, 
        description="Longitude must be within Israel's borders"
    )
):
    """
    On-demand execution of the full fire detection pipeline for a specific coordinate.
    Typically triggered when a user clicks on the dashboard map.
    """
    logging.info(f"Running on-demand fire pipeline for lat={latitude}, lon={longitude}")
    
    # Invoke the same coordinator pipeline used by /api/detected-events.
    pipeline_result = fire_coordinator.run_event_pipeline(latitude, longitude)

    if pipeline_result.get("status") in ("success", "partial"):
        return {
            "status": pipeline_result["status"],
            "message": pipeline_result.get("message"),
            "event_data": build_dashboard_event(pipeline=pipeline_result),
        }
    
    elif pipeline_result.get("status") == "no_event":
        return {"status": "no_event", "message": pipeline_result.get("message")}
    elif pipeline_result.get("status") == "error":
        raise HTTPException(
            status_code=502,
            detail=pipeline_result.get("message", "Pipeline execution failed.")
        )
    else:
        raise HTTPException(
            status_code=500, 
            detail=pipeline_result.get("message", "Internal pipeline error")
        )
