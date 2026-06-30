import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from agents.risk_analysis_agent import analyze_event
from agents.weather_data_agent import WeatherDataAgent
from agents.geospatial_context_agent import GeospatialContextAgent

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = FastAPI()

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

weather_agent = WeatherDataAgent()
geo_agent = GeospatialContextAgent()

@app.get("/")
def read_root():
    return {
        "message": "EcoGuard Agents API is running",
        "status": "success"
    }


@app.get("/api/detected-events")
def get_detected_events():
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
    logging.info(f"Received environmental data request for lat={latitude}, lon={longitude}")
    
    try:
        weather_response = weather_agent.fetch_weather_data(latitude, longitude)
        geo_response = geo_agent.fetch_nearby_context(latitude, longitude, radius_km=2)

        weather_status = weather_response.get("metadata", {}).get("collection_status")
        geo_status = geo_response.get("metadata", {}).get("collection_status")
        
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
