"""
Offline tests for the risk analysis agent.

Both collaborators are injected as fakes, so nothing here reaches the network or
a language model. The fake LLM returns a real ``RiskAssessment`` constructed in
the test, which means it cannot drift from the schema — rename a field and these
fakes stop building.

The properties that matter most, and which most of these tests defend:

- The three detection states (True / False / None) stay distinct.
- Every non-success path yields ``risk_score: None``, never 0 or "low".
- No model call is made when one cannot succeed.
- An answer whose citations do not verify is discarded rather than served.

Run with: pytest
"""

from __future__ import annotations

import json

import pytest

from agents.risk_analysis_agent import (
    RiskAnalysisAgent,
    build_evidence_summary,
    render_excerpts,
    section,
)
from agents.risk_analysis_schemas import RiskAssessment
from services.claude_llm_service import ClaudeProviderError

CHUNK_TEXT = (
    "The minimum radius of defensible space should be 30 feet. Defensible space "
    "should be expanded to compensate for steeper slopes."
)

CHUNK = {
    "chunk_id": "usfa-structure-triage#defensible-space#0",
    "document_id": "usfa-structure-triage",
    "document_title": "Structure Triage in the WUI",
    "source_url": "https://example.invalid/triage",
    "license": "Public domain",
    "heading_path": "Triage > Defensible Space",
    "text": CHUNK_TEXT,
    "score": 9.5,
    "rank": 0,
}


class FakeRetriever:
    """Records queries and returns a fixed chunk list."""

    def __init__(self, chunks=None, available=True) -> None:
        self.chunks = CHUNK_LIST if chunks is None else chunks
        self.available = available
        self.queries: list[str] = []

    def retrieve(self, query, top_k=5):
        self.queries.append(query)
        return list(self.chunks)[:top_k]


CHUNK_LIST = [CHUNK]


class FakeLLM:
    """Returns a prepared model instance, or raises."""

    model = "claude-sonnet-5"

    def __init__(self, result, available=True) -> None:
        self.result = result
        self.available = available
        self.calls: list[dict] = []

    def parse_structured(self, **kwargs):
        self.calls.append(kwargs)

        if isinstance(self.result, Exception):
            raise self.result

        return self.result


def build_valid_assessment(**overrides) -> RiskAssessment:
    """A schema-valid assessment whose citation quotes the fake chunk verbatim."""
    payload = {
        "risk_score": 78,
        "confidence": "medium",
        "primary_drivers": ["very high FWI class", "wind 34 km/h"],
        "explanation": (
            "Conditions are in the very high fire danger class with wind supporting "
            "rapid spread toward the nearest settlement."
        ),
        "evidence_gaps": [],
        "protocol_citations": [
            {
                "chunk_id": CHUNK["chunk_id"],
                "document_title": "Whatever the model called it",
                "quoted_text": "The minimum radius of defensible space should be 30 feet.",
                "supports": "Exposure judgement for the nearby settlement",
            }
        ],
    }
    payload.update(overrides)
    return RiskAssessment(**payload)


def detected_event(**overrides) -> dict:
    """A full Shape A detected event."""
    event = {
        "metadata": {"timestamp": "2026-08-27T09:00:00Z", "collection_status": "success"},
        "event_type": "fire",
        "detected": True,
        "location": {"latitude": 31.9, "longitude": 34.8},
        "detection_confidence": "high",
        "fire_weather_severity": "very_high",
        "satellite_evidence": {
            "source": "NASA FIRMS",
            "hotspots_count": 3,
            "selected_hotspot": {
                "latitude": 31.9,
                "longitude": 34.8,
                "frp": 88.4,
                "acquisition_date": "2026-08-27",
                "satellite": "N20",
                "daynight": "D",
                "confidence": "h",
                "normalized_confidence": "high",
            },
            "hotspots": [],
        },
        "fire_danger": {
            "source": "GWIS/EFFIS",
            "index": "FWI",
            "danger_level": "very_high",
            "fwi_min": 38.0,
            "fwi_max": 50.0,
        },
        "weather_context": {
            "current": {
                "temperature_c": 37.0,
                "humidity_percent": 18,
                "wind_speed_kmh": 34.0,
                "precipitation_mm": 0.0,
                "weather_code": 0,
            },
            "forecast": {"daily": {}},
        },
        "geospatial_context": {
            "terrain_type": None,
            "vegetation_density": None,
            "nearby_settlements": [{"name": "Givat Shmuel", "type": "town"}],
            "nearby_hospitals": [],
            "nearby_fire_stations": [],
            "nearby_police_stations": [],
            "nearby_roads": [{"name": "Route 4", "type": "trunk"}],
        },
        "source_status": {"nasa_firms": "success"},
    }
    event.update(overrides)
    return event


def no_event() -> dict:
    """Shape B: FIRMS ran and found nothing. Note the explicit Nones."""
    return {
        "metadata": {"timestamp": "2026-08-27T09:00:00Z", "collection_status": "success"},
        "event_type": "fire",
        "detected": False,
        "location": {"latitude": 31.9, "longitude": 34.8},
        "detection_confidence": None,
        "fire_weather_severity": None,
        "satellite_evidence": {
            "source": "NASA FIRMS",
            "hotspots_count": 0,
            "selected_hotspot": None,
        },
        "fire_danger": None,
        "weather_context": None,
        "geospatial_context": None,
    }


def failed_detection() -> dict:
    """Shape C: FIRMS could not be reached. No source_status key at all."""
    return {
        "metadata": {"timestamp": "2026-08-27T09:00:00Z", "collection_status": "failed"},
        "event_type": "fire",
        "detected": None,
        "location": {"latitude": 31.9, "longitude": 34.8},
        "detection_confidence": None,
        "fire_weather_severity": None,
        "satellite_evidence": {
            "source": "NASA FIRMS",
            "collection_status": "failed",
            "error": "timeout",
        },
        "fire_danger": None,
        "weather_context": None,
        "geospatial_context": None,
    }


def build_agent(llm=None, retriever=None) -> RiskAnalysisAgent:
    return RiskAnalysisAgent(
        llm_service=llm if llm is not None else FakeLLM(build_valid_assessment()),
        retriever=retriever if retriever is not None else FakeRetriever(),
    )


# --------------------------------------------------------------------------
# Three-shape dispatch
# --------------------------------------------------------------------------


def test_detected_event_is_assessed():
    agent = build_agent()

    result = agent.analyze_event(detected_event())

    assert result["metadata"]["analysis_status"] == "success"
    assert result["risk_score"] == 78
    assert result["risk_level"] == "high"


def test_no_event_is_skipped_without_a_model_call():
    """
    detected is False means FIRMS ran and found nothing.

    That is a valid empty result, not a failure, and it must not cost a model
    call — this is the majority of scans.
    """
    llm = FakeLLM(build_valid_assessment())
    agent = build_agent(llm=llm)

    result = agent.analyze_event(no_event())

    assert result["metadata"]["analysis_status"] == "skipped"
    assert result["metadata"]["reason"] == "no_event"
    assert llm.calls == []


def test_failed_detection_is_distinguished_from_no_event():
    """
    detected is None means FIRMS could not be reached.

    Collapsing this into "no event" would report an outage as an all-clear.
    """
    agent = build_agent()

    result = agent.analyze_event(failed_detection())

    assert result["metadata"]["analysis_status"] == "skipped"
    assert result["metadata"]["reason"] == "detection_unavailable"


@pytest.mark.parametrize(
    "event",
    [
        {"event_type": "flood", "detected": True},
        {"detected": True},
        "not a dict",
        None,
        42,
    ],
)
def test_unsupported_inputs_are_skipped_not_crashed(event):
    agent = build_agent()

    result = agent.analyze_event(event)

    assert result["metadata"]["analysis_status"] == "skipped"
    assert result["metadata"]["reason"] == "unsupported_event"


@pytest.mark.parametrize("event_builder", [no_event, failed_detection])
def test_skipped_assessments_never_fabricate_a_low_score(event_builder):
    """
    The single most important property in this module.

    Absence of a detection is not evidence of low risk, and a provider outage is
    not evidence of safety. A 0 or a "low" here would tell an operator the area
    is clear.
    """
    agent = build_agent()

    result = agent.analyze_event(event_builder())

    assert result["risk_score"] is None
    assert result["risk_level"] is None
    assert result["confidence"] is None
    assert result["explanation"] is None


# --------------------------------------------------------------------------
# Degradation ladder
# --------------------------------------------------------------------------


def test_missing_credentials_fails_before_retrieval():
    """No key means no call and no retrieval work."""
    retriever = FakeRetriever()
    agent = build_agent(
        llm=FakeLLM(build_valid_assessment(), available=False), retriever=retriever
    )

    result = agent.analyze_event(detected_event())

    assert result["metadata"]["analysis_status"] == "failed"
    assert result["error"] == "missing credentials"
    assert retriever.queries == []


def test_empty_retrieval_fails_before_the_model_call():
    """
    Nothing retrieved means nothing to ground an answer in.

    Calling the model anyway would produce a confident, ungrounded answer — the
    exact failure this design refuses.
    """
    llm = FakeLLM(build_valid_assessment())
    agent = build_agent(llm=llm, retriever=FakeRetriever(chunks=[]))

    result = agent.analyze_event(detected_event())

    assert result["metadata"]["analysis_status"] == "failed"
    assert result["error"] == "no protocol match"
    assert result["risk_score"] is None
    assert llm.calls == []


def test_unavailable_corpus_reports_a_distinct_error():
    """A missing corpus is an operator problem; no match is a data problem."""
    agent = build_agent(retriever=FakeRetriever(chunks=[], available=False))

    result = agent.analyze_event(detected_event())

    assert result["error"] == "protocol corpus unavailable"


@pytest.mark.parametrize(
    "kind", ["timeout", "rate limited", "authentication error", "malformed response"]
)
def test_provider_errors_propagate_their_category(kind):
    agent = build_agent(llm=FakeLLM(ClaudeProviderError(kind)))

    result = agent.analyze_event(detected_event())

    assert result["metadata"]["analysis_status"] == "failed"
    assert result["error"] == kind
    assert result["risk_score"] is None


# --------------------------------------------------------------------------
# Citation verification
# --------------------------------------------------------------------------


def test_verified_citation_carries_corpus_provenance():
    agent = build_agent()

    result = agent.analyze_event(detected_event())

    citations = result["grounding"]["citations"]

    assert len(citations) == 1
    assert citations[0]["verified"] is True
    # Provenance comes from the retriever, not from what the model claimed.
    assert citations[0]["document_title"] == "Structure Triage in the WUI"
    assert citations[0]["source_url"] == "https://example.invalid/triage"


def test_fabricated_citation_discards_the_whole_assessment():
    """
    The model answered, but cited a chunk it was never given.

    Keeping the score would present ungrounded reasoning as protocol-derived.
    """
    assessment = build_valid_assessment(
        protocol_citations=[
            {
                "chunk_id": "invented-doc#invented-section#0",
                "document_title": "Authoritative Sounding Source",
                "quoted_text": "Fires shall be extinguished promptly by all units.",
                "supports": "everything",
            }
        ]
    )
    agent = build_agent(llm=FakeLLM(assessment))

    result = agent.analyze_event(detected_event())

    assert result["metadata"]["analysis_status"] == "failed"
    assert result["error"] == "ungrounded response"
    assert result["risk_score"] is None


def test_paraphrased_citation_discards_the_assessment():
    """A real chunk id with invented wording is still ungrounded."""
    assessment = build_valid_assessment(
        protocol_citations=[
            {
                "chunk_id": CHUNK["chunk_id"],
                "document_title": "Structure Triage in the WUI",
                "quoted_text": "Homeowners should clear roughly ten metres of brush.",
                "supports": "exposure",
            }
        ]
    )
    agent = build_agent(llm=FakeLLM(assessment))

    result = agent.analyze_event(detected_event())

    assert result["error"] == "ungrounded response"


def test_partially_verified_citations_keep_the_assessment():
    """
    One good citation is enough; the bad one is dropped and counted.

    Discarding an otherwise well-grounded assessment because of one sloppy
    citation would be too brittle for real use.
    """
    assessment = build_valid_assessment(
        protocol_citations=[
            {
                "chunk_id": CHUNK["chunk_id"],
                "document_title": "t",
                "quoted_text": "The minimum radius of defensible space should be 30 feet.",
                "supports": "real",
            },
            {
                "chunk_id": "made-up#chunk#0",
                "document_title": "t",
                "quoted_text": "Something that was never in the corpus at all here.",
                "supports": "fake",
            },
        ]
    )
    agent = build_agent(llm=FakeLLM(assessment))

    result = agent.analyze_event(detected_event())

    assert result["metadata"]["analysis_status"] == "success"
    assert len(result["grounding"]["citations"]) == 1
    assert result["grounding"]["unverified_citation_count"] == 1


def test_grounding_records_what_was_retrieved():
    """The retrieved ids are reported even for citations the model did not use."""
    agent = build_agent()

    result = agent.analyze_event(detected_event())

    assert result["grounding"]["retrieved_chunk_ids"] == [CHUNK["chunk_id"]]
    assert result["grounding"]["retriever"] == "bm25"


# --------------------------------------------------------------------------
# Query and prompt construction
# --------------------------------------------------------------------------


def test_query_reflects_the_evidence():
    retriever = FakeRetriever()
    agent = build_agent(retriever=retriever)

    agent.analyze_event(detected_event())

    query = retriever.queries[0]

    assert "very high fire danger class" in query
    assert "wind" in query
    assert "humidity" in query
    assert "settlement" in query


def test_query_omits_signals_that_are_absent():
    """A calm, humid event must not retrieve wind and dryness sections."""
    retriever = FakeRetriever()
    agent = build_agent(retriever=retriever)

    event = detected_event(
        weather_context={
            "current": {"temperature_c": 18.0, "humidity_percent": 80, "wind_speed_kmh": 4.0},
            "forecast": {"daily": {}},
        }
    )
    agent.analyze_event(event)

    query = retriever.queries[0]

    assert "wind driven" not in query
    assert "low relative humidity" not in query


def test_prompt_puts_stable_text_in_system_and_variable_text_in_user():
    """
    Prompt caching is a prefix match.

    Retrieved chunks in the system block would invalidate the cache on every
    request, so they must live in the user message.
    """
    llm = FakeLLM(build_valid_assessment())
    agent = build_agent(llm=llm)

    agent.analyze_event(detected_event())

    call = llm.calls[0]

    assert call["system_blocks"][0]["cache_control"] == {"type": "ephemeral"}
    assert CHUNK["chunk_id"] not in call["system_blocks"][0]["text"]
    assert CHUNK["chunk_id"] in call["user_text"]


def test_prompt_states_which_sources_failed():
    """The model must know what it could not see to report gaps honestly."""
    llm = FakeLLM(build_valid_assessment())
    agent = build_agent(llm=llm)

    agent.analyze_event(detected_event(fire_danger={"collection_status": "failed"}))

    assert "GWIS/EFFIS fire weather index" in llm.calls[0]["user_text"]


def test_render_excerpts_tags_every_chunk_with_its_id():
    """The marker format is the contract with the prompt and the verifier."""
    rendered = render_excerpts([CHUNK])

    assert f"[chunk_id: {CHUNK['chunk_id']}]" in rendered
    assert CHUNK_TEXT in rendered


# --------------------------------------------------------------------------
# Robustness on degraded evidence
# --------------------------------------------------------------------------


def test_degraded_shape_a_does_not_raise():
    """
    Even a detected event can arrive with every enrichment source failed.

    fire_danger lacking its usual keys, weather empty, geospatial empty — none
    of that may crash the assessment.
    """
    event = detected_event(
        fire_danger={"collection_status": "failed", "error": "timeout"},
        weather_context={"current": {}, "forecast": {"daily": {}}},
        geospatial_context={},
    )
    agent = build_agent()

    result = agent.analyze_event(event)

    assert result["metadata"]["analysis_status"] == "success"


def test_section_helper_tolerates_explicit_none():
    """Shape B sets sections to None, not {}; .get(key, {}) would still return None."""
    assert section({"a": None}, "a") == {}
    assert section({"a": "string"}, "a") == {}
    assert section(None, "a") == {}
    assert section({"a": {"b": 1}}, "a") == {"b": 1}


def test_evidence_summary_handles_a_bare_event():
    """An event with nothing usable still renders rather than raising."""
    summary = build_evidence_summary({"event_type": "fire", "detected": True})

    assert isinstance(summary, str)
    assert summary


# --------------------------------------------------------------------------
# Boundary contract
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_builder", [detected_event, no_event, failed_detection]
)
def test_result_is_plain_json_serialisable(event_builder):
    """
    No Pydantic model may leak across the agent boundary.

    json.dumps raises on a BaseModel, so this is the cheapest possible guard on
    the house rule that agents exchange plain dicts.
    """
    agent = build_agent()

    result = agent.analyze_event(event_builder())

    json.dumps(result)


def test_success_result_has_every_documented_key():
    agent = build_agent()

    result = agent.analyze_event(detected_event())

    for key in (
        "metadata", "event_type", "location", "risk_score", "risk_level",
        "confidence", "primary_drivers", "explanation", "evidence_gaps",
        "grounding", "error",
    ):
        assert key in result


def test_risk_agent_does_not_emit_planning_fields():
    """Units and plans belong to the planning agent; keep the split clean."""
    agent = build_agent()

    result = agent.analyze_event(detected_event())

    assert "recommended_units" not in result
    assert "response_plan" not in result
