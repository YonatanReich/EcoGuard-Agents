from pathlib import Path

import pytest

from ecoguard.planners.shared.planner import (
    MAX_PLAN_ATTEMPTS,
    UNGROUNDED_RETRY_NOTE,
    EmergencyResponsePlanner,
)
from ecoguard.planners.shared.schemas import (
    EmergencyPlanProposal,
    EmergencyResponsePlanInput,
)
from ecoguard.shared.protocols import ProtocolRetriever

CHUNK_TEXT = (
    "Emergency responders must establish incident command and maintain a safe "
    "approach before beginning operations near the affected area."
)


class FakeRetriever:
    def __init__(self, hazard="fire", *, available=True, chunks=None):
        self.hazard = hazard
        self.available = available
        self.chunks = [
            {
                "chunk_id": f"{hazard}-manual#command#0",
                "document_id": f"{hazard}-manual",
                "document_title": f"{hazard.title()} Manual",
                "source_url": "https://example.invalid/manual",
                "license": "test",
                "heading_path": "Command",
                "text": CHUNK_TEXT,
                "score": 1.0,
                "rank": 0,
            }
        ] if chunks is None else chunks
        self.queries = []

    def retrieve(self, query, top_k=5):
        self.queries.append(query)
        return self.chunks[:top_k]


class FakeLLM:
    model = "test-claude"

    def __init__(self, result, *, available=True):
        self.result = result
        self.available = available
        self.calls = []

    def parse_structured(self, **kwargs):
        self.calls.append(kwargs)
        # A list is a scripted sequence, one entry per attempt.
        result = self.result.pop(0) if isinstance(self.result, list) else self.result
        if isinstance(result, Exception):
            raise result
        return result


def analyzed(hazard="fire", **overrides):
    payload = {
        "hazard_type": hazard,
        "event_description": (
            "Active emergency near a residential area with conditions that may "
            "increase danger to people nearby."
        ),
    }
    payload.update(overrides)
    return EmergencyResponsePlanInput(**payload)


def proposal(chunk_id, *, quoted_text=CHUNK_TEXT, **overrides):
    payload = {
        "recommended_units": ["fire_department", "police"],
        "actions": [
            {
                "action": "Establish incident command and maintain a safe approach.",
                "responsible_unit": "fire_department",
                "timeframe": "immediate",
                "supporting_protocol_chunk_ids": [chunk_id],
            }
        ],
        "plan_summary": "Establish command and coordinate the required emergency unit types.",
        "assumptions": ["Real-world resource availability remains unknown."],
        "protocol_citations": [
            {
                "chunk_id": chunk_id,
                "document_title": "Test Manual",
                "quoted_text": quoted_text,
                "supports": "Incident command and responder safety",
            }
        ],
    }
    payload.update(overrides)
    return EmergencyPlanProposal(**payload)


def planner(hazard="fire", *, llm=None, retriever=None):
    retriever = retriever or FakeRetriever(hazard)
    llm = llm or FakeLLM(proposal(retriever.chunks[0]["chunk_id"]))
    return EmergencyResponsePlanner(llm_service=llm, retriever=retriever)


def test_minimal_fire_input_is_grounded_and_contains_only_unit_types():
    service = planner()
    result = service.plan_response(analyzed())

    assert result.metadata.planning_status == "success"
    assert result.hazard_type == "fire"
    assert result.responding_to is None
    assert result.recommended_units == ["fire_department", "police"]
    assert result.response_actions[0].supporting_protocol_chunk_ids == [
        "fire-manual#command#0"
    ]
    serialized = result.model_dump(mode="json")
    forbidden = {"station_id", "vehicle_id", "dispatch_status", "resource_quantity"}
    assert forbidden.isdisjoint(serialized)
    output_text = result.model_dump_json().lower()
    assert "station x" not in output_text
    assert "vehicle" not in output_text
    assert "dispatched" not in output_text


def test_flood_uses_only_an_injected_flood_test_corpus(tmp_path: Path):
    corpus = tmp_path / "flood"
    corpus.mkdir()
    text = (
        "## Flood command\n\n" + CHUNK_TEXT + " Flood water rescue coordination. " * 12
    )
    (corpus / "flood-test-guidance.md").write_text(text, encoding="utf-8")
    retriever = ProtocolRetriever(corpus_path=corpus, hazard="flood")
    chunk = retriever.retrieve("flood emergency command water rescue", top_k=1)[0]
    llm = FakeLLM(proposal(chunk["chunk_id"]))
    service = EmergencyResponsePlanner(llm_service=llm, retriever=retriever)

    result = service.plan_response(
        analyzed("flood", event_description="Flood water is entering occupied streets.")
    )

    assert result.metadata.planning_status == "success"
    assert result.hazard_type == "flood"
    assert all("fire" not in item for item in result.grounding.retrieved_chunk_ids)
    assert result.responding_to is None
    assert "population" not in result.model_dump_json().lower()


def test_earthquake_uses_only_the_earthquake_protocol_corpus():
    retriever = ProtocolRetriever(hazard="earthquake")
    analysis = analyzed(
        "earthquake",
        event_description="GSI reported an earthquake; actual damage is unknown.",
    )
    chunk = retriever.retrieve(
        EmergencyResponsePlanner.build_query(analysis), top_k=1
    )[0]
    llm = FakeLLM(proposal(chunk["chunk_id"], quoted_text=chunk["text"]))
    result = EmergencyResponsePlanner(
        llm_service=llm,
        retriever=retriever,
    ).plan_response(analysis)

    assert result.metadata.planning_status == "success", result.error
    assert result.hazard_type == "earthquake"
    assert result.responding_to is None
    assert result.grounding.citations[0]["verified"] is True
    assert all(
        item.startswith((
            "israel-police-multi-agency-emergency-response",
            "home-front-command-earthquake-preparedness",
            "nema-earthquake-preparedness",
        ))
        for item in result.grounding.retrieved_chunk_ids
    )


def test_production_flood_corpus_reaches_claude_with_verified_grounding():
    retriever = ProtocolRetriever(hazard="flood")
    chunk = retriever.retrieve(
        "underground parking flood possible trapped civilians", top_k=1
    )[0]
    llm = FakeLLM(
        proposal(
            chunk["chunk_id"],
            quoted_text=chunk["text"][:200].strip(),
            actions=[
                {
                    "action": "Conduct initial reconnaissance for trapped civilians safely.",
                    "responsible_unit": "fire_department",
                    "timeframe": "immediate",
                    "supporting_protocol_chunk_ids": [chunk["chunk_id"]],
                }
            ],
        )
    )
    service = EmergencyResponsePlanner(llm_service=llm, retriever=retriever)

    result = service.plan_response(
        analyzed("flood", event_description="Flood water threatens occupied streets.")
    )

    assert retriever.available is True
    assert result.metadata.planning_status == "success"
    assert result.hazard_type == "flood"
    assert result.response_actions[0].supporting_protocol_chunk_ids == [
        chunk["chunk_id"]
    ]
    assert llm.calls
    prompt = llm.calls[0]["user_text"]
    assert "Jurisdiction: Israel" in prompt
    assert "Local adaptation required: false" in prompt


def test_production_flood_unknown_citation_is_labelled_not_discarded():
    """Same contract as the parametrised case, against the real flood corpus."""
    retriever = ProtocolRetriever(hazard="flood")
    chunk = retriever.retrieve("flooded road closure police", top_k=1)[0]
    payload = proposal(
        chunk["chunk_id"], quoted_text=chunk["text"][:200].strip()
    ).model_dump()
    payload["protocol_citations"][0]["chunk_id"] = "invented-flood#chunk#0"
    llm = FakeLLM(EmergencyPlanProposal(**payload))

    result = EmergencyResponsePlanner(
        llm_service=llm, retriever=retriever
    ).plan_response(
        analyzed("flood", event_description="A flooded road requires closure.")
    )

    assert result.metadata.planning_status == "partial"
    assert result.response_actions
    assert result.grounding.protocol_grounded is False
    assert result.grounding.citations == []
    assert result.limitations[0].startswith("NOT PROTOCOL-VERIFIED")
    assert result.metadata.reason == "ungrounded_response"


def test_empty_event_description_is_skipped_before_claude():
    raw = {"hazard_type": "fire", "event_description": "   "}
    llm = FakeLLM(proposal("fire-manual#command#0"))
    retriever = FakeRetriever("fire")
    service = EmergencyResponsePlanner(llm_service=llm, retriever=retriever)

    result = service.plan_response(raw)

    assert result.metadata.planning_status == "skipped"
    assert result.metadata.reason == "invalid_planner_input"
    assert llm.calls == []
    assert retriever.queries == []


def test_optional_context_is_preserved_without_risk_recalculation():
    llm = FakeLLM(proposal("fire-manual#command#0"))
    service = planner(llm=llm)
    result = service.plan_response(
        analyzed(
            incident_id="fire-42",
            location={"latitude": 31.9, "longitude": 34.8},
            risk_context={"score": 0.82, "scale": "upstream_custom"},
            evidence_gaps=["Population unavailable"],
            limitations=["Remote observation"],
            additional_context={"severity_hint": "critical", "source": "analyzer"},
        )
    )

    assert result.incident_id == "fire-42"
    assert result.location.model_dump() == {"latitude": 31.9, "longitude": 34.8}
    assert result.responding_to == {"score": 0.82, "scale": "upstream_custom"}
    assert result.evidence_gaps == ["Population unavailable"]
    assert result.limitations == ["Remote observation"]
    prompt = llm.calls[0]["user_text"]
    assert "upstream_custom" in prompt
    assert '"severity_hint": "critical"' in prompt


@pytest.mark.parametrize("failure", ["unknown_chunk", "bad_quote", "bad_action"])
def test_evidence_that_does_not_verify_is_labelled_rather_than_discarded(failure):
    """Unverifiable evidence no longer costs the operator the whole plan.

    This used to assert a blank card: status "failed", no units, no actions.
    That was the single largest source of incidents with no advice attached,
    and a plausible plan an operator can weigh beats nothing. What is kept is
    the labelling — the plan says it is unverified, and the citations that
    failed are not shown, so invented text never borrows the protocol's
    authority.
    """
    retriever = FakeRetriever("fire")
    payload = proposal(retriever.chunks[0]["chunk_id"]).model_dump()
    if failure == "unknown_chunk":
        payload["protocol_citations"][0]["chunk_id"] = "invented#chunk#0"
    elif failure == "bad_quote":
        payload["protocol_citations"][0]["quoted_text"] = (
            "This sentence is not present anywhere in the retrieved protocol."
        )
    else:
        payload["actions"][0]["supporting_protocol_chunk_ids"] = ["invented#chunk#0"]
    llm = FakeLLM(EmergencyPlanProposal(**payload))
    service = EmergencyResponsePlanner(llm_service=llm, retriever=retriever)

    result = service.plan_response(analyzed())

    assert result.metadata.planning_status == "partial"
    assert result.response_actions, "the operator still gets something to act on"
    # ...but never silently, and never with evidence that did not hold up.
    assert result.limitations, "a partial plan must say what could not be verified"
    if not result.grounding.protocol_grounded:
        assert result.grounding.citations == []
        assert result.limitations[0].startswith("NOT PROTOCOL-VERIFIED")
    # Still retried once before settling, rather than looping.
    assert len(llm.calls) == MAX_PLAN_ATTEMPTS


def test_ungrounded_first_attempt_is_retried_and_recovered():
    retriever = FakeRetriever("fire")
    chunk_id = retriever.chunks[0]["chunk_id"]
    ungrounded = proposal(chunk_id).model_dump()
    ungrounded["protocol_citations"][0]["chunk_id"] = "invented#chunk#0"
    llm = FakeLLM(
        [EmergencyPlanProposal(**ungrounded), proposal(chunk_id)]
    )
    service = EmergencyResponsePlanner(llm_service=llm, retriever=retriever)

    result = service.plan_response(analyzed())

    assert result.metadata.planning_status == "success"
    assert result.grounding.attempts == 2
    assert result.response_actions
    assert len(llm.calls) == 2
    # The retry names the failure instead of resampling blind, and does so
    # without disturbing the cached system prefix.
    assert UNGROUNDED_RETRY_NOTE in llm.calls[1]["user_text"]
    assert llm.calls[0]["system_blocks"] == llm.calls[1]["system_blocks"]


def test_missing_optional_context_is_not_fabricated():
    llm = FakeLLM(proposal("fire-manual#command#0"))
    service = planner(llm=llm)
    result = service.plan_response(
        analyzed(additional_context={}, evidence_gaps=["Population unavailable"])
    )

    assert result.evidence_gaps == ["Population unavailable"]
    prompt = llm.calls[0]["user_text"].lower()
    assert "roads_at_risk" not in prompt
    assert "critical_infrastructure" not in prompt
    assert "affected_population" not in prompt


def test_wrong_hazard_retriever_is_rejected_without_fallback():
    retriever = FakeRetriever("fire")
    llm = FakeLLM(proposal(retriever.chunks[0]["chunk_id"]))
    result = EmergencyResponsePlanner(
        llm_service=llm, retriever=retriever
    ).plan_response(analyzed("flood"))
    assert result.error == "protocol_hazard_mismatch"
    assert llm.calls == []
    assert retriever.queries == []


def test_unsupported_hazard_is_rejected_before_protocol_selection():
    raw = analyzed().model_dump(mode="json")
    raw["hazard_type"] = "tsunami"
    with pytest.raises(ValueError, match="unsupported emergency hazard"):
        planner().plan_response(raw)


def test_claude_unavailable_fails_without_generic_recommendations():
    retriever = FakeRetriever("fire")
    llm = FakeLLM(None, available=False)
    result = planner(llm=llm, retriever=retriever).plan_response(analyzed())
    assert result.metadata.planning_status == "failed"
    assert result.error == "missing_credentials"
    assert result.recommended_units == []
    assert result.response_actions == []
    assert retriever.queries == []
