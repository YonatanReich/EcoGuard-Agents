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

from ecoguard.analyzers.emergency.fire.risk_analysis_agent import (
    RiskAnalysisAgent,
    build_evidence_summary,
    render_excerpts,
    section,
)
from ecoguard.shared.schemas import RiskAssessment
from ecoguard.shared.llm import ClaudeProviderError

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


VALID_SITUATIONAL_CONTEXT = {
    "area_type": "wildland_urban_interface",
    "area_type_basis": (
        "One settlement tagged place=town within the search radius, beside open "
        "ground, with a trunk road running past it."
    ),
    "population_band": "1k_to_10k",
    "population_basis": "settlement_type_inference",
    "evacuation_consideration": "localised_evacuation",
    "context_gaps": [],
}


def build_valid_assessment(**overrides) -> RiskAssessment:
    """A schema-valid assessment whose citation quotes the fake chunk verbatim."""
    payload = {
        "risk_score": 78,
        "confidence": "medium",
        "situational_context": dict(VALID_SITUATIONAL_CONTEXT),
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


# --------------------------------------------------------------------------
# Situational facts — Python-computed, no model involved
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("12000", 12000),
        ("~5,000", 5000),          # OSM tags are free text
        ("1,234", 1234),
        ("5000-6000", 5000),       # a range yields the conservative lower bound
        ("approx 800", 800),
        (7500, 7500),
        ("n/a", None),
        ("", None),
        (None, None),
        (True, None),              # a bool is not a population
        (-5, None),
    ],
)
def test_population_tag_parsing(tag, expected):
    """A junk tag yields None, never 0 — it is unparseable, not empty."""
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import parse_population_tag

    assert parse_population_tag(tag) == expected


@pytest.mark.parametrize("geospatial", [None, {}, "not a dict"])
def test_absent_geospatial_yields_null_counts_not_zero(geospatial):
    """
    The single most important assertion in this file.

    Zero means the search ran and found nothing. None means it never looked.
    Collapsing the two would let "we never checked for settlements" be read as
    "there are no settlements nearby" — which, in a response plan, is the
    difference between evacuating a town and not knowing it is there.
    """
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_situational_facts

    facts = build_situational_facts({"geospatial_context": geospatial})

    assert facts["geospatial_available"] is False

    for key in (
        "settlements_count", "hospitals_count", "fire_stations_count",
        "police_stations_count", "roads_count", "tagged_population_total",
        "settlement_types", "road_classes", "settlements_with_population_tag",
    ):
        assert facts[key] is None, f"{key} must be None when nothing was searched"


def test_geospatial_that_ran_and_found_nothing_yields_zero():
    """The other half of the distinction: a real empty result is 0, not None."""
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_situational_facts

    facts = build_situational_facts(
        {"geospatial_context": {"nearby_settlements": [], "nearby_roads": []}}
    )

    assert facts["geospatial_available"] is True
    assert facts["settlements_count"] == 0
    assert facts["roads_count"] == 0
    # Still None: no settlement carried a tag, which is not a population of zero.
    assert facts["tagged_population_total"] is None


def test_situational_facts_count_and_summarise():
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_situational_facts

    facts = build_situational_facts(detected_event())

    assert facts["settlements_count"] == 1
    assert facts["settlement_types"] == ["town"]
    assert facts["fire_stations_count"] == 0
    assert facts["road_classes"] == ["trunk"]


def test_tagged_population_sums_only_what_parsed():
    """Settlements without a usable tag are excluded from both the sum and the count."""
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_situational_facts

    facts = build_situational_facts(
        {
            "geospatial_context": {
                "nearby_settlements": [
                    {"name": "A", "type": "town", "population": "21,000"},
                    {"name": "B", "type": "village", "population": "junk"},
                    {"name": "C", "type": "village"},
                ]
            }
        }
    )

    assert facts["tagged_population_total"] == 21000
    assert facts["settlements_with_population_tag"] == 1
    assert facts["settlements_count"] == 3


def test_evidence_summary_renders_settlement_type_and_population():
    """
    Without this the model cannot ground a population estimate at all.

    The summary previously rendered names only, so the OSM population tag —
    the one grounded basis available — never reached the prompt.
    """
    summary = build_evidence_summary(detected_event())

    assert "Givat Shmuel" in summary
    assert "town" in summary


def test_evidence_summary_carries_the_derived_counts():
    summary = build_evidence_summary(detected_event())

    assert "Derived counts:" in summary
    assert "Fire stations found: 0" in summary


def test_evidence_summary_states_when_geospatial_never_ran():
    """The prompt must distinguish 'searched, found none' from 'did not search'."""
    summary = build_evidence_summary(detected_event(geospatial_context=None))

    assert "DID NOT RUN" in summary
    assert "not the same as zero" in summary


# --------------------------------------------------------------------------
# Non-satellite report evidence
# --------------------------------------------------------------------------


REPORT_EVIDENCE = {
    "source": "Telegram public channels",
    "reports_count": 6,
    "channels": ["fireisrael7777", "Israel_Police_100"],
    "first_report_at": "2026-08-30T12:14:00Z",
    "latest_report_at": "2026-08-30T13:47:00Z",
    "candidate_confidence": 0.95,
    "matched_terms": ["שריפה", "מתפשטת"],
    "location_precision": "settlement",
    "geocode_confidence": 0.7,
    "corroborated_by_satellite": False,
}


def test_report_evidence_is_rendered_when_present():
    """
    Otherwise a reported event looks like a detection with no evidence at all.

    The satellite block is truthfully empty for such an event, so without this
    the model would see nothing supporting it.
    """
    summary = build_evidence_summary(detected_event(report_evidence=REPORT_EVIDENCE))

    assert "Telegram public channels" in summary
    assert "Reports received: 6" in summary
    assert "Corroborated by satellite: NO" in summary


def test_report_evidence_is_absent_for_a_satellite_event():
    """No empty section for the ordinary case."""
    summary = build_evidence_summary(detected_event())

    assert "Non-satellite report evidence" not in summary


def test_report_evidence_tolerates_partial_fields():
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import render_report_evidence

    rendered = render_report_evidence(
        {"report_evidence": {"source": "Telegram", "reports_count": 2}}
    )

    assert "Telegram" in rendered
    assert "Reports received: 2" in rendered


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


# --------------------------------------------------------------------------
# Gap-filling web search
# --------------------------------------------------------------------------


def test_search_tool_is_offered_by_default():
    llm = FakeLLM(build_valid_assessment())
    agent = build_agent(llm=llm)

    agent.analyze_event(detected_event())

    tools = llm.calls[0]["tools"]

    assert tools[0]["type"] == "web_search_20260209"
    assert tools[0]["max_uses"] == 3
    assert "cbs.gov.il" in tools[0]["allowed_domains"]


def test_search_can_be_disabled_and_then_no_tools_are_sent():
    """
    None rather than an empty list.

    An empty `tools` list would still change the request shape; None omits the
    parameter entirely, which is what keeps a search-free call identical to one
    made before the capability existed.
    """
    llm = FakeLLM(build_valid_assessment())
    agent = RiskAnalysisAgent(
        llm_service=llm, retriever=FakeRetriever(), enable_web_search=False
    )

    agent.analyze_event(detected_event())

    assert llm.calls[0]["tools"] is None


def test_verified_web_findings_reach_the_assessment():
    assessment = build_valid_assessment(
        web_findings=[
            {
                "query": "Yakir population",
                "fact": "Yakir had a population of 2,742 in 2024.",
                "source_url": "https://en.wikipedia.org/wiki/Yakir",
                "source_title": "Yakir — Wikipedia",
                "informs": "population_band",
            }
        ]
    )
    agent = build_agent(llm=FakeLLM(assessment))

    result = agent.analyze_event(detected_event())

    assert len(result["web_findings"]) == 1
    assert result["grounding"]["web_search"]["findings_verified"] == 1
    assert result["grounding"]["web_search"]["findings_dropped"] == 0


def test_off_allowlist_findings_are_dropped_from_the_assessment():
    """
    The API restricts what can be read; the model reports what it found.

    A finding attributed to a source outside the allowlist must not reach an
    operator, whether it came from a misattribution or an invention.
    """
    assessment = build_valid_assessment(
        web_findings=[
            {
                "query": "population",
                "fact": "A forum post claims 40,000 residents.",
                "source_url": "https://randomforum.example/thread/12",
                "source_title": "Forum",
                "informs": "population_band",
            }
        ]
    )
    agent = build_agent(llm=FakeLLM(assessment))

    result = agent.analyze_event(detected_event())

    assert result["web_findings"] == []
    assert result["grounding"]["web_search"]["findings_dropped"] == 1


def test_web_sourced_population_without_a_surviving_finding_is_downgraded():
    """
    A confident band must not outlive the evidence that supported it.

    The model claims a web-sourced population, but the finding behind it was
    dropped for an off-allowlist source. Leaving the basis as `web_search` would
    present an unsupported figure as a sourced one.
    """
    assessment = build_valid_assessment(
        situational_context={
            **VALID_SITUATIONAL_CONTEXT,
            "population_band": "10k_to_100k",
            "population_basis": "web_search",
        },
        web_findings=[
            {
                "query": "population",
                "fact": "Claimed 40,000 residents from an unlisted source.",
                "source_url": "https://randomforum.example/thread/12",
                "source_title": "Forum",
                "informs": "population_band",
            }
        ],
    )
    agent = build_agent(llm=FakeLLM(assessment))

    context = agent.analyze_event(detected_event())["situational_context"]

    assert context["population_basis"] == "settlement_type_inference"
    assert any("no verified finding" in gap for gap in context["context_gaps"])


def test_web_sourced_population_with_a_supporting_finding_is_kept():
    assessment = build_valid_assessment(
        situational_context={
            **VALID_SITUATIONAL_CONTEXT,
            "population_basis": "web_search",
        },
        web_findings=[
            {
                "query": "Yakir population",
                "fact": "Yakir had a population of 2,742 in 2024.",
                "source_url": "https://en.wikipedia.org/wiki/Yakir",
                "source_title": "Yakir — Wikipedia",
                "informs": "population_band",
            }
        ],
    )
    agent = build_agent(llm=FakeLLM(assessment))

    context = agent.analyze_event(detected_event())["situational_context"]

    assert context["population_basis"] == "web_search"


# --------------------------------------------------------------------------
# Situational context on the assessment
# --------------------------------------------------------------------------


def test_successful_assessment_carries_situational_context_and_derived_facts():
    agent = build_agent()

    context = agent.analyze_event(detected_event())["situational_context"]

    assert context["area_type"] == "wildland_urban_interface"
    assert context["derived"]["settlements_count"] == 1
    assert context["derived"]["fire_stations_count"] == 0


@pytest.mark.parametrize("event_builder", [no_event, failed_detection])
def test_skipped_assessment_has_no_situational_context(event_builder):
    """
    None, not {}.

    No assessment was produced, so there is no judgement about the area either.
    An empty object would read as "we looked and found nothing notable".
    """
    agent = build_agent()

    result = agent.analyze_event(event_builder())

    assert result["situational_context"] is None
    assert result["web_findings"] == []


def test_risk_semantics_distinguishes_this_score_from_the_ml_prediction():
    """
    Guards against a genuinely dangerous confusion.

    FireRiskPredictionAgent also emits `risk_score` and `risk_level`, but its
    score is a 0.0-1.0 probability that a fire *starts*, on a three-level scale.
    This agent's score is 0-100 severity of a fire that *already exists*, on a
    four-level scale. A consumer that mistook 0.85 for 85 would be wrong by two
    orders of magnitude, so both agents must label their semantics.
    """
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import RISK_SEMANTICS

    agent = build_agent()
    result = agent.analyze_event(detected_event())

    assert result["risk_semantics"] == "detected_event_operational_risk"
    assert RISK_SEMANTICS != "estimated_fire_risk"


@pytest.mark.parametrize("event_builder", [no_event, failed_detection])
def test_risk_semantics_is_present_even_without_a_score(event_builder):
    """A consumer must be able to tell which kind of risk is missing."""
    agent = build_agent()

    result = agent.analyze_event(event_builder())

    assert result["risk_score"] is None
    assert result["risk_semantics"] == "detected_event_operational_risk"


def test_assessment_carries_a_stable_event_id():
    """
    The join key for everything downstream.

    Same hotspot means same id across scans, so the assessment, the plan and
    the map marker all refer to one event without a shared database.
    """
    agent = build_agent()

    first = agent.analyze_event(detected_event())
    second = agent.analyze_event(detected_event())

    assert isinstance(first["event_id"], str)
    assert first["event_id"] == second["event_id"]


def test_event_id_changes_with_the_hotspot():
    """Two different fires must not collide onto one id."""
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_event_id

    other = detected_event()
    other["satellite_evidence"] = {
        **other["satellite_evidence"],
        "selected_hotspot": {
            **other["satellite_evidence"]["selected_hotspot"],
            "latitude": 30.1,
            "longitude": 34.9,
        },
    }

    assert build_event_id(detected_event()) != build_event_id(other)


def test_event_id_tolerates_the_no_event_and_failed_shapes():
    """Those shapes have no hotspot; deriving an id must not raise."""
    from ecoguard.analyzers.emergency.fire.risk_analysis_agent import build_event_id

    assert isinstance(build_event_id(no_event()), str)
    assert isinstance(build_event_id(failed_detection()), str)
    assert isinstance(build_event_id({}), str)


def test_risk_agent_does_not_emit_planning_fields():
    """Units and plans belong to the planning agent; keep the split clean."""
    agent = build_agent()

    result = agent.analyze_event(detected_event())

    assert "recommended_units" not in result
    assert "response_plan" not in result
