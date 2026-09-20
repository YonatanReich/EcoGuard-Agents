"""Flood analysis/planning policy at the shared incident-dispatch boundary."""

from datetime import datetime, timedelta, timezone

from ecoguard.analyzers.emergency.flood.event_analyzer import FloodEventAnalyzer
from ecoguard.analyzers.emergency.flood.incident_handler import FloodRoadIncidentHandler
from ecoguard.coordinator.dispatcher import dispatch_incidents
from ecoguard.response_planner.emergency.schemas import EmergencyResponsePlan


AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
THRESHOLDS = [20.0, 35.0, 50.0, 80.0, 120.0, 170.0]


def _signal(
    *,
    observed_at=AT,
    station_id=417,
    cell_id="31.75:35.20",
    severity=3,
    previous_discharge=52.0,
    current_discharge=60.0,
):
    return {
        "cell_id": cell_id,
        "observed_at": observed_at.isoformat(),
        "hazard": "flood",
        "variable": "discharge",
        "value": current_discharge,
        "unit": "m3/s",
        "source": "water_authority_hydrometric_observations",
        "confidence": 0.9,
        "location": {
            "latitude": 31.75,
            "longitude": 35.2,
            "precision_m": 100.0,
            "method": "hydrometric_station",
        },
        "evidence": {
            "source_station_id": station_id,
            "stream_id": 82,
            "timestamp": observed_at.isoformat(),
            "current_discharge": current_discharge,
            "severity_level": severity,
            "threshold_vector_m3s": THRESHOLDS,
            "recent_discharges_m3s": [previous_discharge, current_discharge],
        },
    }


def _incident(*signals):
    return {
        "id": "INC-FLOOD-1",
        "status": "open",
        "primary_hazard": "flood",
        "hazards": ["flood"],
        "queues": ["emergency"],
        "signals": list(signals),
    }


def _successful_plan(incident_id):
    return EmergencyResponsePlan(
        metadata={
            "timestamp": AT.isoformat(),
            "agent": "fake-flood-planner",
            "planning_status": "success",
        },
        incident_id=incident_id,
        hazard_type="flood",
        location={"latitude": 31.75, "longitude": 35.2},
        responding_to={"hydrologic_severity_level": 3},
        plan_summary="Maintain command and restrict access near the flooded stream.",
        recommended_units=["police"],
        response_actions=[{
            "action": "Restrict access near the affected stream crossing.",
            "responsible_unit": "police",
            "timeframe": "immediate",
            "supporting_protocol_chunk_ids": ["flood-test#response#0"],
        }],
        grounding={
            "retrieved_chunk_ids": ["flood-test#response#0"],
            "citations": [{"chunk_id": "flood-test#response#0"}],
        },
    )


class FakePlanner:
    def __init__(self):
        self.calls = []

    def plan_response(self, plan_input):
        self.calls.append(plan_input)
        return _successful_plan(plan_input.incident_id)


def _dispatch(incident, planner):
    handler = FloodRoadIncidentHandler(
        analyzer=FloodEventAnalyzer(clock=lambda: AT + timedelta(hours=1)),
        planner=planner,
        clock=lambda: AT + timedelta(hours=1),
    )
    return dispatch_incidents(
        [incident],
        registry={("flood", "emergency"): handler},
        at=AT + timedelta(hours=1),
    )[0]


def test_initial_flood_analysis_refreshes_plan_and_requests_allocation():
    planner = FakePlanner()
    result = _dispatch(_incident(_signal()), planner)

    assert result.status == "success"
    assert result.handler == "flood_emergency_analysis_planning"
    assert result.analysis_status == "success"
    assert result.planner_status == "success"
    assert result.analysis_result.change_assessment.change_type == "initial"
    assert result.response_refresh_required is True
    assert result.requires_resource_allocation is True
    assert result.preserve_existing_response is False
    assert len(planner.calls) == 1
    assert planner.calls[0].hazard_type == "flood"


def test_escalation_refreshes_the_response_immediately():
    planner = FakePlanner()
    result = _dispatch(
        _incident(
            _signal(observed_at=AT, severity=3, current_discharge=60.0),
            _signal(
                observed_at=AT + timedelta(minutes=10),
                severity=4,
                previous_discharge=60.0,
                current_discharge=85.0,
            ),
        ),
        planner,
    )

    assert result.analysis_result.change_assessment.change_type == "escalated"
    assert result.response_refresh_required is True
    assert result.requires_resource_allocation is True
    assert len(planner.calls) == 1


def test_deescalation_preserves_plan_and_allocations_without_planner_call():
    planner = FakePlanner()
    result = _dispatch(
        _incident(
            _signal(observed_at=AT, severity=5, current_discharge=125.0),
            _signal(
                observed_at=AT + timedelta(minutes=10),
                severity=4,
                previous_discharge=125.0,
                current_discharge=110.0,
            ),
        ),
        planner,
    )

    assert result.status == "success"
    assert result.analysis_result.change_assessment.change_type == "deescalated"
    assert result.analysis_result.current_state.severity_level == 4
    assert result.planner_status == "skipped"
    assert result.response_refresh_required is False
    assert result.requires_resource_allocation is False
    assert result.preserve_existing_response is True
    assert planner.calls == []


def test_same_band_update_preserves_existing_response():
    planner = FakePlanner()
    result = _dispatch(
        _incident(
            _signal(observed_at=AT, severity=4, current_discharge=85.0),
            _signal(
                observed_at=AT + timedelta(minutes=10),
                severity=4,
                previous_discharge=85.0,
                current_discharge=90.0,
            ),
        ),
        planner,
    )

    assert result.analysis_result.change_assessment.change_type == "no_material_change"
    assert result.response_refresh_required is False
    assert result.requires_resource_allocation is False
    assert result.preserve_existing_response is True
    assert planner.calls == []


def test_spatial_expansion_refreshes_response_even_without_higher_severity():
    planner = FakePlanner()
    result = _dispatch(
        _incident(
            _signal(observed_at=AT, severity=4, current_discharge=85.0),
            _signal(
                observed_at=AT + timedelta(minutes=10),
                station_id=418,
                cell_id="31.80:35.25",
                severity=4,
                previous_discharge=82.0,
                current_discharge=85.0,
            ),
        ),
        planner,
    )

    assert result.analysis_result.change_assessment.change_type == "updated"
    assert result.response_refresh_required is True
    assert result.requires_resource_allocation is True
    assert len(planner.calls) == 1


def test_unavailable_analysis_does_not_call_planner_or_allocator():
    planner = FakePlanner()
    result = _dispatch(_incident(), planner)

    assert result.status == "partial"
    assert result.analysis_status == "unavailable"
    assert result.planner_status == "skipped"
    assert result.requires_resource_allocation is False
    assert result.preserve_existing_response is True
    assert planner.calls == []
