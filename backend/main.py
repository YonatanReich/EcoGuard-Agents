from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    return {
        "events": [
            {
                "id": 1,
                "type": "wildfire",
                "title": "Mock wildfire risk event",
                "description": "High wildfire risk detected near a dry vegetation area.",
                "latitude": 32.0853,
                "longitude": 34.7818,
                "risk_score": 82,
                "risk_level": "high",
                "recommended_units": [
                    "fire_department",
                    "municipal_emergency_team",
                    "police"
                ],
                "response_plan": [
                    "Verify the event using available environmental data.",
                    "Alert nearby emergency response units.",
                    "Monitor wind direction and nearby sensitive infrastructure."
                ]
            }
        ]
    }