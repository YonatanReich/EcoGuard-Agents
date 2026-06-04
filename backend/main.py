from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.risk_analysis_agent import analyze_event

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