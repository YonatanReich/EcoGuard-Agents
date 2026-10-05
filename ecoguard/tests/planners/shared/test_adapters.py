import pytest

from ecoguard.planners.shared.adapters import (
    OperationalAnalysisUnavailable,
    build_fire_plan_input,
)
from ecoguard.tests.analyzers.test_risk_analysis_agent import detected_event


def successful_assessment(**overrides) -> dict:
    """A minimal successful operational-risk result for adapter tests."""
    assessment = {
        "metadata": {"analysis_status": "success"},
        "event_id": "a3f19c2b8d04",
        "event_type": "fire",
        "location": {"latitude": 31.9, "longitude": 34.8},
        "risk_score": 78,
        "risk_level": "high",
        "risk_semantics": "detected_event_operational_risk",
        "confidence": "medium",
        "primary_drivers": ["very high FWI class", "wind 34 km/h"],
        "explanation": "Very high fire danger with wind supporting rapid spread.",
        "evidence_gaps": [],
    }
    assessment.update(overrides)
    return assessment


def test_fire_adapter_maps_only_operational_risk_and_preserves_context():
    event = detected_event()
    risk = successful_assessment(
        evidence_gaps=["No verified crew availability"],
        situational_context={"area_type": "wildland_urban_interface"},
    )
    result = build_fire_plan_input(
        event,
        risk,
        spread_analysis={
            "risk_score": 91,
            "risk_semantics": "fire_spread_forecast",
            "limits": ["Unsuppressed spread"],
        },
    )

    assert result.risk_context["risk_score"] == 78
    assert result.risk_context["risk_semantics"] == "detected_event_operational_risk"
    assert "Very high fire danger" in result.event_description
    assert "Operational risk score: 78 out of 100" in result.event_description
    assert "Primary drivers:" in result.event_description
    assert "Situational context:" in result.event_description
    assert result.evidence_gaps == ["No verified crew availability"]
    assert result.limitations == ["Unsuppressed spread"]
    assert result.additional_context["fire_spread_forecast"]["risk_score"] == 91


@pytest.mark.parametrize(
    "risk",
    [
        {},
        successful_assessment(risk_semantics="fire_spread_forecast"),
        successful_assessment(risk_score=None),
    ],
)
def test_fire_adapter_rejects_missing_or_wrong_operational_analysis(risk):
    with pytest.raises(OperationalAnalysisUnavailable):
        build_fire_plan_input(detected_event(), risk)


def test_fire_adapter_does_not_promote_proximity_to_shared_exposure_fields():
    result = build_fire_plan_input(detected_event(), successful_assessment())
    root = result.model_dump(mode="json")
    assert "affected_population" not in root
    assert "roads_at_risk" not in root
    assert "critical_infrastructure" not in root
    assert "detected_event" in root["additional_context"]
