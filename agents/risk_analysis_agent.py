"""
Risk Analysis Agent

Responsible for turning a detected event type into a risk assessment:
a numeric score, a severity level, the emergency units that should be
activated, and a step-by-step response plan.

This is currently a stub. It returns hard-coded values per event type
rather than deriving anything from live weather or geospatial data. It
exists so the API contract and the dashboard can be built and tested
before the real scoring model is written.

Consumed by: backend.main.get_detected_events
"""


# Severity thresholds and unit lists are inlined in the returned dicts on
# purpose while this is a stub. Once scoring is real they should move into
# a proper rules table keyed by event type.


def analyze_event(event_type):
    """
    Produce a risk assessment for a single detected event.

    Args:
        event_type (str): Event category, e.g. "wildfire". Any unrecognized
            value falls through to a conservative medium-risk default.

    Returns:
        dict: Risk assessment with the keys:
            - risk_score (int): 0-100, higher means more dangerous.
            - risk_level (str): "high" | "medium" — human-readable band.
            - recommended_units (list[str]): Emergency services to activate.
            - response_plan (list[str]): Ordered actions for the operator.
            - explanation (str): Plain-language reason for the score, shown
              to the user in the dashboard.
    """
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

    # Unknown event types still get a valid assessment so callers never have
    # to handle a None. Medium is the safe default: not ignorable, not alarming.
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
