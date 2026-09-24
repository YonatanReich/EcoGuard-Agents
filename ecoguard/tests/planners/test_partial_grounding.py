"""A plan is kept for the part that grounded, and labelled when none of it did.

The planner used to discard a whole plan if any citation failed to verify, so
one paraphrased quote out of eight left an incident with no advice at all. That
was the largest single source of blank cards. These pin the three outcomes.
"""

from ecoguard.planners.shared.planner import EmergencyResponsePlanner


CHUNK = {
    "chunk_id": "c1",
    "document_id": "orders",
    "text": "Establish a safety zone and confirm escape routes before engaging.",
    "document_title": "Standard Orders",
    "source_url": "https://example.test/orders",
    "heading_path": "Safety",
}
OTHER = {
    "chunk_id": "c2",
    "document_id": "aerial",
    "text": "Request aerial support when the head of the fire is unapproachable.",
    "document_title": "Aerial Doctrine",
    "source_url": "https://example.test/aerial",
    "heading_path": "Aerial",
}


def _payload(citations, actions):
    return {
        "plan_summary": "Hold the flank and protect the settlement edge.",
        "recommended_units": ["fire_department"],
        "protocol_citations": citations,
        "actions": actions,
        "assumptions": [],
    }


def _action(text, supporting):
    return {
        "action": text,
        "responsible_unit": "fire_department",
        "timeframe": "immediate",
        "supporting_protocol_chunk_ids": supporting,
    }


def _input():
    from ecoguard.planners.shared.schemas import EmergencyResponsePlanInput

    return EmergencyResponsePlanInput.model_validate({
        "incident_id": "INC-TEST-1",
        "hazard_type": "fire",
        "location": {"latitude": 32.1, "longitude": 34.9},
        "event_description": "A fire is spreading toward the settlement edge.",
        "risk_context": {},
        "evidence_gaps": [],
        "limitations": [],
    })


def test_a_fully_grounded_plan_is_success():
    """Unchanged behaviour when everything verifies."""
    planner = EmergencyResponsePlanner.__new__(EmergencyResponsePlanner)
    planner.llm_service = type("S", (), {"model": "test"})()

    payload = _payload(
        [{"chunk_id": "c1", "quoted_text": "confirm escape routes", "supports": "x"}],
        [_action("Establish a safety zone before engaging.", ["c1"])],
    )
    plan, dropped = planner._verified_plan(_input(), payload, [CHUNK], 0)

    assert plan is not None
    assert plan.metadata.planning_status == "success"
    assert dropped == 0
    assert len(plan.response_actions) == 1


def test_one_bad_citation_no_longer_destroys_the_whole_plan():
    """The case this change exists for: keep what grounded, drop what did not."""
    planner = EmergencyResponsePlanner.__new__(EmergencyResponsePlanner)
    planner.llm_service = type("S", (), {"model": "test"})()

    payload = _payload(
        [
            {"chunk_id": "c1", "quoted_text": "confirm escape routes", "supports": "x"},
            {"chunk_id": "c2", "quoted_text": "invented text never written", "supports": "y"},
        ],
        [
            _action("Establish a safety zone before engaging.", ["c1"]),
            _action("Request aerial support immediately.", ["c2"]),
        ],
    )
    plan, dropped = planner._verified_plan(_input(), payload, [CHUNK, OTHER], 0)

    assert plan is not None, "a plan with one good half must survive"
    assert plan.metadata.planning_status == "partial"
    assert dropped == 1
    # The grounded action is kept; the one resting on the bad citation is gone.
    assert len(plan.response_actions) == 1
    assert "safety zone" in plan.response_actions[0].action
    assert any("Partly grounded" in item for item in plan.limitations)


def test_nothing_grounded_returns_none_so_the_caller_retries():
    """A plan with no surviving action drives the retry rather than shipping."""
    planner = EmergencyResponsePlanner.__new__(EmergencyResponsePlanner)
    planner.llm_service = type("S", (), {"model": "test"})()

    payload = _payload(
        [{"chunk_id": "c1", "quoted_text": "text that was never written", "supports": "x"}],
        [_action("Request aerial support immediately.", ["c1"])],
    )
    plan, _ = planner._verified_plan(_input(), payload, [CHUNK], 0)

    assert plan is None


def test_the_advisory_fallback_keeps_the_plan_but_strips_the_citations():
    """Your ask: advice labelled unverified beats a blank card.

    The citations go, because they are the part that failed. Leaving them would
    lend invented text the authority of the protocol it did not come from.
    """
    planner = EmergencyResponsePlanner.__new__(EmergencyResponsePlanner)
    planner.llm_service = type("S", (), {"model": "test"})()

    payload = _payload(
        [{"chunk_id": "c1", "quoted_text": "text that was never written", "supports": "x"}],
        [_action("Request aerial support immediately.", ["c1"])],
    )
    plan = planner._advisory_plan(_input(), payload, [CHUNK], dropped=1)

    assert plan is not None
    assert plan.metadata.planning_status == "partial"
    assert plan.metadata.reason == "ungrounded_response"
    assert plan.grounding.citations == [], "false citations must not be shown"
    assert plan.grounding.protocol_grounded is False
    assert plan.limitations[0].startswith("NOT PROTOCOL-VERIFIED")
    assert len(plan.response_actions) == 1
