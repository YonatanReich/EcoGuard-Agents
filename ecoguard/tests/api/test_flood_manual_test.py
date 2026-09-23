"""No-network, no-database contracts for the manual Flood pipeline path."""

from datetime import datetime, timedelta, timezone

from ecoguard.api.flood_manual_test import (
    MemoryIncidentStore,
    SyntheticPlanner,
    _observations,
)
from ecoguard.coordinator.agent import coordinate
from ecoguard.detectors.flood.detection_agent import FloodDetectionAgent
from ecoguard.planners.shared.schemas import EmergencyResponsePlanInput


START = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
STATION = {
    "source_station_id": 417,
    "station_name": "Contract station",
    "cell_id": "risk-05000m-r0040-c0012",
    "latitude": 31.75,
    "longitude": 35.2,
    "stream_id": 82,
    "thresholds_m3s": [20.0, 35.0, 50.0, 80.0, 120.0, 170.0],
}


def _signals(scenario):
    observations = _observations(scenario, STATION, START)
    return FloodDetectionAgent().evaluate(
        cell_id=STATION["cell_id"],
        observations=observations,
        stream_ids={417: 82},
        target_observed_at={row["observed_at"] for row in observations},
    )


def test_below_threshold_noise_never_reaches_downstream_pipeline():
    assert _signals("below_threshold") == []


def test_confirmed_scenario_uses_real_detector_and_memory_coordinator():
    signals = _signals("confirmed_q10")
    assert len(signals) == 1
    assert signals[0].evidence["severity_level"] == 3

    store = MemoryIncidentStore()
    result = coordinate(
        signals,
        at=signals[-1].observed_at + timedelta(minutes=1),
        incident_store=store,
    )
    assert result.created == ["INC-TEST-20260921-0001"]
    assert result.emergency[0]["signals"][0]["hazard"] == "flood"


def test_quiet_period_closes_only_after_three_hours():
    signals = _signals("ended")
    store = MemoryIncidentStore()
    coordinate(signals, at=signals[-1].observed_at, incident_store=store)

    exact = coordinate(
        [], at=signals[-1].observed_at + timedelta(hours=3), incident_store=store
    )
    after = coordinate(
        [],
        at=signals[-1].observed_at + timedelta(hours=3, seconds=1),
        incident_store=store,
    )
    assert exact.closed == []
    assert after.closed == ["INC-TEST-20260921-0001"]


def test_synthetic_planner_returns_real_schema_without_a_model_client():
    planner = SyntheticPlanner()
    plan = planner.plan_response(EmergencyResponsePlanInput(
        hazard_type="flood",
        incident_id="INC-TEST-1",
        location={"latitude": 31.75, "longitude": 35.2},
        event_description="Confirmed Q10 Flood detector state.",
        risk_context={
            "risk_semantics": "detected_event_operational_risk",
            "risk_score": 40,
            "risk_level": "medium",
            "confidence": "high",
            "hydrologic_severity_level": 3,
            "return_period_years": 10,
            "alert_level": "active",
        },
    ))
    assert plan.metadata.planning_status == "success"
    assert plan.metadata.model is None
    assert plan.recommended_units == [
        "fire_department", "police", "medical_services"
    ]
