"""
EcoGuard Agents — FastAPI application entry point.

Responsible for exposing the agent layer over HTTP and for combining the
output of several agents into the single unified response the frontend
dashboard consumes. This module owns transport concerns only — CORS, input
validation, status codes and error masking. All domain logic lives in the
agents package.

Endpoints:
    GET /                       Health check.
    GET /api/detected-events    Currently-detected risk events (mock data).
    GET /api/environmental-data Live weather + geospatial context for one
                                coordinate.

Run locally with:
    uvicorn backend.main:app --reload
"""

import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from agents.risk_analysis_agent import analyze_event
from agents.weather_data_agent import WeatherDataAgent
from agents.geospatial_context_agent import GeospatialContextAgent
from agents.coordinator import FireCoordinator

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
fire_coordinator = FireCoordinator()

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


@app.get("/api/detected-events")
def get_detected_events():
    """
    Return the list of currently detected risk events.

    Mock endpoint: it always returns exactly one hard-coded wildfire event
    near Tel Aviv, with its risk fields filled in by the risk analysis agent.
    It exists so the dashboard's map markers and event counter have something
    to render before real event detection is implemented.

    Returns:
        dict: {"events": [...]} where each event carries its identity, its
            map coordinates, and the risk analysis agent's assessment
            (score, level, recommended units, response plan, explanation).
    """
    event_type = "wildfire"
    analysis = analyze_event(event_type)

    return {
        "events": [
            {
                "id": 1,
                "type": event_type,
                "title": "Mock wildfire risk event",
                "description": "High wildfire risk detected near a dry vegetation area.",
                "latitude": 32.0853,
                "longitude": 34.7818,
                "risk_score": analysis["risk_score"],
                "risk_level": analysis["risk_level"],
                "recommended_units": analysis["recommended_units"],
                "response_plan": analysis["response_plan"],
                "explanation": analysis["explanation"]
            }
        ]
    }

@app.get("/api/environmental-data")
def get_environmental_data(
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
    
    # Envoke coordinator
    pipeline_result = fire_coordinator.run_event_pipeline(latitude, longitude)
    
    if pipeline_result.get("status") == "success":
        return {
            "status": "success",
            "event_data": {
                "type": pipeline_result["event_type"],
                "latitude": pipeline_result["location"]["latitude"],
                "longitude": pipeline_result["location"]["longitude"],
                "risk_score": pipeline_result["risk_assessment"]["score"],
                "risk_level": pipeline_result["risk_assessment"]["level"],
                "explanation": pipeline_result["risk_assessment"]["explanation"],
                "allocated_resources": pipeline_result["allocated_resources"],
                "response_plan": pipeline_result["response_plan"]
            }
        }
    
    # החזרת שגיאה מסודרת או הודעת "לא נמצא אירוע" ללקוח
    elif pipeline_result.get("status") == "no_event":
        return {"status": "no_event", "message": pipeline_result.get("message")}
    else:
        raise HTTPException(
            status_code=500, 
            detail=pipeline_result.get("message", "Internal pipeline error")
        )
