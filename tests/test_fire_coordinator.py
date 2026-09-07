from unittest.mock import MagicMock
from agents.coordinator import FireCoordinator
from agents.resource_allocation_agent import ResourceAllocationAgent


def make_pipeline(detected=True):
    detection, risk, allocation, planning = [MagicMock() for _ in range(4)]
    detection.detect_fire.return_value = {"detected": detected, "location": {"latitude": 31, "longitude": 35}, "geospatial_context": {}}
    risk.analyze_event.return_value = {"metadata": {"analysis_status": "success"}}
    allocation.allocate_resources.return_value = {"status": "success", "allocated_units": {}}
    planning.plan_response.return_value = {"metadata": {"planning_status": "success"}, "response_actions": [], "recommended_units": ["fire_department"], "responding_to": {"risk_level": "high"}}
    risk.build_skipped_assessment.return_value = {
        "metadata": {"analysis_status": "skipped"},
        "risk_score": None,
        "risk_level": None,
    }
    planning.build_skipped_plan.return_value = {
        "metadata": {"planning_status": "skipped"},
        "recommended_units": [],
        "response_actions": [],
    }
    return FireCoordinator(detection_agent=detection, risk_agent=risk, allocation_agent=allocation, planning_agent=planning), detection, risk, allocation, planning


def test_chain_passes_real_results_in_order():
    coordinator, detection, risk, allocation, planning = make_pipeline()
    parent = MagicMock()
    for name, agent in [("detection", detection), ("risk", risk), ("allocation", allocation), ("planning", planning)]:
        parent.attach_mock(agent, name)
    result = coordinator.run_event_pipeline(31, 35)
    assert result["status"] == "success"
    assert [call[0] for call in parent.mock_calls] == ["detection.detect_fire", "risk.analyze_event", "planning.plan_response", "allocation.allocate_resources"]
    risk.analyze_event.assert_called_once_with(detection.detect_fire.return_value)
    planning.plan_response.assert_called_once_with(detection.detect_fire.return_value, risk.analyze_event.return_value)
    assert allocation.allocate_resources.call_args.args[2] is planning.plan_response.return_value


def test_no_event_does_not_allocate():
    coordinator, detection, risk, allocation, planning = make_pipeline(False)
    assert coordinator.run_event_pipeline(31, 35)["status"] == "no_event"
    risk.build_skipped_assessment.assert_called_once_with(
        detection.detect_fire.return_value, "no_event"
    )
    planning.build_skipped_plan.assert_called_once_with(
        "no_event", detection.detect_fire.return_value
    )
    allocation.allocate_resources.assert_not_called()


def test_unsupported_event_does_not_detect():
    coordinator, detection, *_ = make_pipeline()
    assert coordinator.run_event_pipeline(31, 35, "flood")["status"] == "error"
    detection.detect_fire.assert_not_called()


def test_detection_only_skips_expensive_calls():
    coordinator, _, risk, allocation, planning = make_pipeline()
    risk.build_skipped_assessment.return_value = {"metadata": {"analysis_status": "skipped"}}
    planning.build_skipped_plan.return_value = {"response_actions": []}
    coordinator.run_event_pipeline(31, 35, include_analysis=False)
    risk.analyze_event.assert_not_called()
    allocation.allocate_resources.assert_not_called()
    planning.plan_response.assert_not_called()
    risk.build_skipped_assessment.assert_called_once()
    planning.build_skipped_plan.assert_called_once()


def test_failed_risk_skips_allocation_and_reports_partial():
    coordinator, detection, risk, allocation, planning = make_pipeline()
    risk.analyze_event.return_value = {"metadata": {"analysis_status": "failed"}}
    assert coordinator.run_event_pipeline(31, 35)["status"] == "partial"
    planning.build_skipped_plan.assert_called_once_with(
        "risk_analysis_unavailable", detection.detect_fire.return_value
    )
    allocation.allocate_resources.assert_not_called()


def test_failed_detection_reports_error():
    coordinator, _, _, allocation, _ = make_pipeline(None)
    assert coordinator.run_event_pipeline(31, 35)["status"] == "error"
    allocation.allocate_resources.assert_not_called()


def test_failed_planning_skips_allocation():
    coordinator, _, _, allocation, planning = make_pipeline()
    planning.plan_response.return_value = {"metadata": {"planning_status": "failed"}, "response_actions": []}
    assert coordinator.run_event_pipeline(31, 35)["status"] == "partial"
    allocation.allocate_resources.assert_not_called()


def test_response_preserves_actions_recipients_and_partial_failure():
    coordinator, _, _, allocation, planning = make_pipeline()
    actions = [
        {"action": "Close the road and divert traffic.", "responsible_unit": "police", "timeframe": "immediate"},
        {"action": "Confirm escape routes.", "responsible_unit": "fire_department", "timeframe": "ongoing"},
    ]
    plan = {**planning.plan_response.return_value, "response_actions": actions,
            "plan_summary": "Protect access to the incident.", "assumptions": ["Road conditions need verification."],
            "grounding": {"citations": [{"chunk_id": "test-citation"}]}}
    planning.plan_response.return_value = plan
    resources = {"status": "partial", "allocated_units": {"fire_stations": [{"name": "Station A"}], "police_stations": []},
                 "shortages": {"police_station": 1}, "errors": [{"reason": "search_failed"}]}
    allocation.allocate_resources.return_value = resources
    result = coordinator.run_event_pipeline(31,35)
    unified = result
    assert unified["status"] == "partial"
    assert unified["planning"]["response_actions"] == actions
    assert unified["allocated_resources"] == resources
    assert unified["planning"]["plan_summary"] == plan["plan_summary"]
    assert unified["planning"]["assumptions"] == plan["assumptions"]
    assert "response_actions" not in unified
    assert "plan_summary" not in unified
    assert "response_plan" not in unified


def test_failed_plan_has_no_operational_instructions():
    coordinator, _, _, _, planning = make_pipeline()
    planning.plan_response.return_value = {"metadata": {"planning_status": "failed"}, "response_actions": []}
    unified = coordinator.run_event_pipeline(31,35)
    assert unified["planning"]["metadata"]["planning_status"] == "failed"
    assert unified["planning"]["response_actions"] == []
    assert unified["allocated_resources"]["status"] == "skipped"


def test_full_flow_uses_real_allocator_for_only_recommended_unit_type():
    detection = MagicMock()
    risk = MagicMock()
    planning = MagicMock()
    geospatial = MagicMock()

    detection.detect_fire.return_value = {
        "detected": True,
        "location": {"latitude": 31, "longitude": 35},
        "geospatial_context": {
            "nearby_roads": [{"name": "Route 4", "ref": "4"}]
        },
    }
    risk.analyze_event.return_value = {
        "metadata": {"analysis_status": "success"},
        "risk_score": 42,
        "risk_level": "medium",
    }
    planning.plan_response.return_value = {
        "metadata": {"planning_status": "success"},
        "recommended_units": ["medical_services"],
        "responding_to": {"risk_level": "medium"},
        "response_actions": [],
    }
    geospatial.fetch_facilities.return_value = {
        "status": "success",
        "facilities": [
            {
                "name": "Hospital A",
                "latitude": 31.01,
                "longitude": 35,
                "osm_type": "node",
                "osm_id": 123,
            }
        ],
    }
    coordinator = FireCoordinator(
        detection_agent=detection,
        risk_agent=risk,
        planning_agent=planning,
        allocation_agent=ResourceAllocationAgent(geospatial_agent=geospatial),
    )

    result = coordinator.run_event_pipeline(31, 35)

    assert result["status"] == "success"
    assert set(result["allocated_resources"]["allocated_units"]) == {"hospitals"}
    hospital = result["allocated_resources"]["allocated_units"]["hospitals"][0]
    assert hospital["name"] == "Hospital A"
    assert "osm_id" not in hospital
    assert "osm_type" not in hospital
    assert result["nearby_roads"] == [{"name": "Route 4", "ref": "4"}]
    assert "nearby_roads" not in result["allocated_resources"]
    geospatial.fetch_facilities.assert_called_once_with(31.0, 35.0, "hospital", 10)


def test_full_flow_skips_allocation_when_plan_recommends_no_units():
    coordinator, _, _, _, planning = make_pipeline()
    geospatial = MagicMock()
    coordinator.resource_allocation_agent = ResourceAllocationAgent(
        geospatial_agent=geospatial
    )
    planning.plan_response.return_value = {
        "metadata": {"planning_status": "success"},
        "recommended_units": [],
        "responding_to": {"risk_level": "low"},
        "response_actions": [],
    }

    result = coordinator.run_event_pipeline(31, 35)

    assert result["status"] == "success"
    assert result["allocated_resources"]["allocation_needed"] is False
    assert result["allocated_resources"]["allocated_units"] == {}
    geospatial.fetch_facilities.assert_not_called()
