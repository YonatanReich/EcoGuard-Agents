from ecoguard.tests.planners.shared.test_planner import analyzed, planner


def test_shared_plan_exposes_future_allocation_requirements_without_allocating():
    analysis = analyzed(
        incident_id="fire-incident-1",
        location={"latitude": 31.9, "longitude": 34.8},
        risk_context={
            "risk_score": 78,
            "risk_level": "high",
            "risk_semantics": "detected_event_operational_risk",
        },
    )
    result = planner().plan_response(analysis).model_dump(mode="json")

    assert result["incident_id"]
    assert result["location"] == {"latitude": 31.9, "longitude": 34.8}
    assert result["responding_to"] == {
        "risk_score": 78,
        "risk_level": "high",
        "risk_semantics": "detected_event_operational_risk",
    }
    assert result["recommended_units"]
    assert result["response_actions"][0]["timeframe"] == "immediate"
    assert not {
        "required_resources",
        "resource_quantities",
        "allocated_units",
        "stations",
        "vehicles",
        "shortages",
        "dispatch_status",
    } & set(result)
