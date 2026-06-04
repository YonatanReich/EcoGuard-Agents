def analyze_event(event_type):
    if event_type == "wildfire":
        return {
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
            ],
            "explanation": "Wildfire risk is high because dry vegetation and environmental conditions may allow fire to spread quickly."
        }

    return {
        "risk_score": 50,
        "risk_level": "medium",
        "recommended_units": [
            "municipal_emergency_team"
        ],
        "response_plan": [
            "Verify the event details.",
            "Monitor the area for changes."
        ],
        "explanation": "A default medium risk level was assigned because the event type is not yet fully supported."
    }