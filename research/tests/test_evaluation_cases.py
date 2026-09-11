"""
Offline validation of the artificial fire evaluation cases.

These cases are hand-authored inputs that get replayed through the response
planner, so an authoring mistake in one of them would surface later as a
pipeline failure and be debugged in the wrong place. Everything checkable
without a model is checked here.

The most valuable test is the citation one: a frozen assessment carrying a
quotation that does not appear in the corpus would feed the planner a fabricated
citation, which is precisely what the rest of the system exists to prevent.

Run with: pytest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.risk_analysis_agent import build_event_id
from agents.risk_analysis_schemas import SituationalContext
from services.protocol_retrieval_service import ProtocolRetriever, verify_citations

CASES_DIR = Path(__file__).resolve().parents[2] / "data" / "evaluation" / "fire_cases"

EXPECTED_CASE_COUNT = 8

REQUIRED_KEYS = {
    "case_id", "title", "hazard", "probes", "notes",
    "expected_behaviour_notes", "detected_event", "risk_assessment",
}


def load_cases() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CASES_DIR.glob("*.json"))
    ]


CASES = load_cases()
CASE_IDS = [case["case_id"] for case in CASES]


@pytest.fixture(scope="module")
def corpus():
    return ProtocolRetriever(hazard="fire")


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def test_expected_number_of_cases():
    assert len(CASES) == EXPECTED_CASE_COUNT


def test_case_ids_are_unique():
    assert len(CASE_IDS) == len(set(CASE_IDS))


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_case_has_required_keys(case):
    assert REQUIRED_KEYS <= set(case)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_case_is_json_serialisable(case):
    json.dumps(case)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_detected_event_shape(case):
    """Both planner arguments must be present and well formed."""
    event = case["detected_event"]

    assert event["event_type"] == "fire"
    assert event["detected"] in (True, False, None)
    assert "latitude" in event["location"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_event_id_matches_the_detected_event(case):
    """
    The join key must actually join.

    A mismatch would break correlation between assessment, plan and marker in a
    way that only shows up downstream.
    """
    assert case["risk_assessment"]["event_id"] == build_event_id(case["detected_event"])


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_hazard_is_fire(case):
    assert case["hazard"] == "fire"


# --------------------------------------------------------------------------
# Grounding — the important one
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_frozen_citation_verifies_against_the_real_corpus(case, corpus):
    """
    A hand-authored quotation that is not in the corpus is a fabricated citation.

    It would reach the planner looking exactly like a real one, and the failure
    would be attributed to the pipeline rather than to the case file. The build
    script extracts quotes mechanically for this reason; this test is what keeps
    them honest if someone edits a case by hand.
    """
    citations = (case["risk_assessment"].get("grounding") or {}).get("citations") or []

    verified, dropped = verify_citations(citations, corpus.chunks)

    assert dropped == 0, f"{case['case_id']} has {dropped} unverifiable citation(s)"
    assert len(verified) == len(citations)


def test_the_suite_actually_cites_something():
    """Guards against a build that silently produced citation-free cases."""
    total = sum(
        len((case["risk_assessment"].get("grounding") or {}).get("citations") or [])
        for case in CASES
    )

    assert total >= 12


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_situational_context_validates_where_present(case):
    """A frozen context must satisfy the same schema a live one would."""
    context = case["risk_assessment"].get("situational_context")

    if context is None:
        return

    SituationalContext(
        **{key: value for key, value in context.items() if key != "derived"}
    )


# --------------------------------------------------------------------------
# The spread — the suite has to probe more than one thing
# --------------------------------------------------------------------------


def test_exactly_one_case_gates_the_pipeline():
    """
    detected None means FIRMS could not be reached, so nothing can be planned.

    This is the case that must cost nothing at all.
    """
    gated = [c for c in CASES if c["detected_event"]["detected"] is None]

    assert len(gated) == 1
    assert gated[0]["risk_assessment"]["metadata"]["analysis_status"] != "success"
    assert gated[0]["risk_assessment"]["risk_score"] is None


def test_all_other_cases_are_plannable():
    """Everything except the gate case must reach the planner."""
    plannable = [
        c for c in CASES
        if c["risk_assessment"]["metadata"]["analysis_status"] == "success"
    ]

    assert len(plannable) == EXPECTED_CASE_COUNT - 1


def test_severity_spans_the_scale():
    """
    A suite where everything is critical tests nothing about proportionality.

    Over-response is as much a failure as under-response, so the suite needs
    cases where the correct answer is minimal.
    """
    scores = [
        c["risk_assessment"]["risk_score"]
        for c in CASES
        if c["risk_assessment"]["risk_score"] is not None
    ]

    assert min(scores) < 25, "no low-risk case: nothing tests over-response"
    assert max(scores) >= 80, "no critical case: nothing tests full mobilisation"


def test_area_types_are_varied():
    """The corpus covers wildland and structural doctrine; probe both."""
    area_types = {
        (c["risk_assessment"].get("situational_context") or {}).get("area_type")
        for c in CASES
    }

    assert "urban_residential" in area_types
    assert "wildland_urban_interface" in area_types
    assert "open_natural" in area_types
    assert "unknown" in area_types


def test_evidence_quality_is_varied():
    """Degraded, stale and non-satellite evidence each appear at least once."""
    events = [c["detected_event"] for c in CASES]

    assert any(e.get("geospatial_context") is None for e in events), "no degraded case"
    assert any("report_evidence" in e for e in events), "no non-satellite case"
    assert any(
        (e.get("satellite_evidence") or {}).get("hotspots_count") == 0
        and e["detected"] is True
        for e in events
    ), "no case with an event asserted without a hotspot"


def test_a_case_has_geospatial_that_ran_and_found_nothing():
    """
    Distinct from geospatial having failed.

    This is the case where population_band none_nearby is a grounded answer
    rather than an unknown, and where over-response is the failure mode.
    """
    empty_but_ran = [
        c for c in CASES
        if isinstance(c["detected_event"].get("geospatial_context"), dict)
        and not c["detected_event"]["geospatial_context"].get("nearby_settlements")
        and not c["detected_event"]["geospatial_context"].get("nearby_roads")
    ]

    assert empty_but_ran
    context = empty_but_ran[0]["risk_assessment"]["situational_context"]
    assert context["derived"]["settlements_count"] == 0      # ran, found none
    assert context["population_band"] == "none_nearby"


def test_degraded_case_reports_null_counts_not_zero():
    """The null-versus-zero distinction, pinned in the frozen data itself."""
    degraded = [
        c for c in CASES if c["detected_event"].get("geospatial_context") is None
        and c["risk_assessment"]["metadata"]["analysis_status"] == "success"
    ]

    assert degraded
    derived = degraded[0]["risk_assessment"]["situational_context"]["derived"]

    assert derived["geospatial_available"] is False
    assert derived["settlements_count"] is None
    assert derived["tagged_population_total"] is None


def test_probes_cover_the_intended_ground():
    """Every case declares what it is for, and the union covers the design."""
    probes = {probe for case in CASES for probe in case["probes"]}

    for expected in ("proportionality", "refusal", "honesty-under-missing-data"):
        assert expected in probes, f"no case probes {expected}"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_author_notes_are_present_and_non_trivial(case):
    """
    These never reach the judge, but they are how a reader knows what is
    artificial about a case and what a sound answer looks like.
    """
    assert len(case["notes"]) > 60
    assert len(case["expected_behaviour_notes"]) > 60
