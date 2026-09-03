"""
Offline tests for the risk analysis and response planning schemas.

These models are the contract between the language model and the rest of the
system, so the tests focus on what the schema must *reject*. A schema that
accepts a malformed answer silently is worse than no schema at all.

Run with: pytest
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.risk_analysis_schemas import (
    ProtocolCitation,
    ResponseAction,
    ResponsePlan,
    RiskAssessment,
    risk_level_for_score,
)

VALID_CITATION = {
    "chunk_id": "usfa-structure-triage#2-defensible-space#0",
    "document_title": "Structure Triage in the Wildland/Urban Interface",
    "quoted_text": "The minimum radius of defensible space should be 30 feet.",
    "supports": "Defensible space threshold used in the exposure judgement",
}


def build_assessment(**overrides) -> dict:
    """Return a valid RiskAssessment payload with optional overrides."""
    payload = {
        "risk_score": 78,
        "confidence": "medium",
        "primary_drivers": ["very high FWI danger class", "wind speed 34 km/h"],
        "explanation": (
            "Fire weather conditions are in the very high danger class and wind "
            "speed supports rapid spread toward nearby settlements."
        ),
        "evidence_gaps": [],
        "protocol_citations": [dict(VALID_CITATION)],
    }
    payload.update(overrides)
    return payload


def build_plan(**overrides) -> dict:
    """Return a valid ResponsePlan payload with optional overrides."""
    payload = {
        "recommended_units": ["fire_department", "police"],
        "actions": [
            {
                "action": "Establish incident command and confirm escape routes.",
                "responsible_unit": "fire_department",
                "timeframe": "immediate",
            },
            {
                "action": "Close the access road and stage traffic control.",
                "responsible_unit": "police",
                "timeframe": "within_1_hour",
            },
        ],
        "plan_summary": "Contain the flank and protect the nearest settlement.",
        "assumptions": [],
        "protocol_citations": [dict(VALID_CITATION)],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# risk_level_for_score
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (100, "critical"),
        (80, "critical"),   # lower boundary of critical
        (79, "high"),
        (50, "high"),       # lower boundary of high
        (49, "medium"),
        (25, "medium"),     # lower boundary of medium
        (24, "low"),
        (0, "low"),
    ],
)
def test_risk_level_bands_at_boundaries(score, expected):
    """Band edges are where an off-by-one would hide, so test them directly."""
    assert risk_level_for_score(score) == expected


def test_none_score_yields_none_level():
    """
    Absence of a score must not become "low".

    A skipped or failed analysis means we do not know the risk. Reporting "low"
    would tell an operator the area is safe, which is the exact fabrication this
    design exists to prevent.
    """
    assert risk_level_for_score(None) is None


# --------------------------------------------------------------------------
# ProtocolCitation
# --------------------------------------------------------------------------


def test_valid_citation_parses():
    citation = ProtocolCitation(**VALID_CITATION)

    assert citation.chunk_id == VALID_CITATION["chunk_id"]


def test_citation_strips_whitespace():
    """Chunk ids must compare cleanly against the retrieved set."""
    citation = ProtocolCitation(
        **{**VALID_CITATION, "chunk_id": "  doc#section#0  "}
    )

    assert citation.chunk_id == "doc#section#0"


def test_single_word_quote_is_rejected():
    """A one-word 'quotation' is not evidence the source was read."""
    with pytest.raises(ValidationError):
        ProtocolCitation(**{**VALID_CITATION, "quoted_text": "fire"})


def test_empty_chunk_id_is_rejected():
    with pytest.raises(ValidationError):
        ProtocolCitation(**{**VALID_CITATION, "chunk_id": ""})


# --------------------------------------------------------------------------
# RiskAssessment
# --------------------------------------------------------------------------


def test_valid_assessment_parses():
    assessment = RiskAssessment(**build_assessment())

    assert assessment.risk_score == 78
    assert assessment.confidence == "medium"


@pytest.mark.parametrize("score", [-1, 101, 1000])
def test_out_of_range_scores_are_rejected(score):
    with pytest.raises(ValidationError):
        RiskAssessment(**build_assessment(risk_score=score))


def test_uncited_assessment_is_rejected():
    """
    This is the structural grounding guarantee.

    An answer with no citations cannot validate, so it can never reach the API
    response as if it were protocol-derived.
    """
    with pytest.raises(ValidationError):
        RiskAssessment(**build_assessment(protocol_citations=[]))


def test_assessment_without_drivers_is_rejected():
    """A score with no stated drivers is unreviewable."""
    with pytest.raises(ValidationError):
        RiskAssessment(**build_assessment(primary_drivers=[]))


def test_trivial_explanation_is_rejected():
    with pytest.raises(ValidationError):
        RiskAssessment(**build_assessment(explanation="High risk."))


def test_unknown_confidence_value_is_rejected():
    with pytest.raises(ValidationError):
        RiskAssessment(**build_assessment(confidence="very-high"))


def test_assessment_has_no_risk_level_field():
    """
    risk_level is derived in Python, never requested from the model.

    If someone adds it back to the schema, the incoherent-pair failure mode
    returns with it.
    """
    assert "risk_level" not in RiskAssessment.model_fields


def test_realistic_length_output_is_accepted():
    """
    Regression guard for a bug that discarded good answers.

    `explanation` was originally capped at 1200 characters. Live Sonnet 5 runs
    on the same input produced 989, 1174 and 1290 characters, so about one call
    in three was rejected as "malformed response" — the model was billed, the
    assessment was correct and well-cited, and the schema threw it away.

    These lengths sit above anything observed live. If someone tightens the caps
    again, this fails.
    """
    assessment = RiskAssessment(
        **build_assessment(
            explanation="A" * 2000,
            primary_drivers=[f"driver {i}" for i in range(8)],
            evidence_gaps=[f"gap {i}" for i in range(8)],
        )
    )

    assert len(assessment.explanation) == 2000
    assert len(assessment.primary_drivers) == 8


def test_a_full_chunk_can_be_quoted():
    """
    A chunk is up to ~1200 characters and quoting one in full is correct.

    The original 400-character cap on quoted_text would have rejected an honest
    citation of a long protocol passage.
    """
    citation = ProtocolCitation(**{**VALID_CITATION, "quoted_text": "B" * 1200})

    assert len(citation.quoted_text) == 1200


def test_realistic_plan_length_is_accepted():
    """Same guard for the planning side."""
    plan = ResponsePlan(
        **build_plan(
            plan_summary="C" * 1500,
            actions=[
                {
                    "action": "D" * 500,
                    "responsible_unit": "fire_department",
                    "timeframe": "immediate",
                }
            ],
            recommended_units=["fire_department"],
        )
    )

    assert len(plan.plan_summary) == 1500


def test_evidence_gaps_defaults_to_empty():
    payload = build_assessment()
    payload.pop("evidence_gaps")

    assert RiskAssessment(**payload).evidence_gaps == []


# --------------------------------------------------------------------------
# ResponsePlan
# --------------------------------------------------------------------------


def test_valid_plan_parses():
    plan = ResponsePlan(**build_plan())

    assert plan.recommended_units == ["fire_department", "police"]
    assert len(plan.actions) == 2


def test_action_assigned_to_unrecommended_unit_is_rejected():
    """
    The cross-field coherence check.

    An action owned by a unit nobody dispatched leaves an operator with a task
    and no responder.
    """
    payload = build_plan(
        actions=[
            {
                "action": "Request aerial water drops on the fire head.",
                "responsible_unit": "aerial_firefighting",
                "timeframe": "immediate",
            }
        ]
    )

    with pytest.raises(ValidationError, match="unrecommended units"):
        ResponsePlan(**payload)


def test_unknown_unit_id_is_rejected():
    """The closed vocabulary means the frontend never sees an unmappable unit."""
    with pytest.raises(ValidationError):
        ResponsePlan(**build_plan(recommended_units=["space_force"]))


def test_unknown_timeframe_is_rejected():
    payload = build_plan()
    payload["actions"][0]["timeframe"] = "eventually"

    with pytest.raises(ValidationError):
        ResponsePlan(**payload)


def test_uncited_plan_is_rejected():
    with pytest.raises(ValidationError):
        ResponsePlan(**build_plan(protocol_citations=[]))


def test_plan_without_actions_is_rejected():
    with pytest.raises(ValidationError):
        ResponsePlan(**build_plan(actions=[]))


def test_trivially_short_action_is_rejected():
    payload = build_plan()
    payload["actions"][0]["action"] = "Go"

    with pytest.raises(ValidationError):
        ResponsePlan(**payload)


def test_action_has_no_order_field():
    """List position is the order; an index field would only add failure modes."""
    assert "order" not in ResponseAction.model_fields


# --------------------------------------------------------------------------
# Boundary contract
# --------------------------------------------------------------------------


def test_model_dump_is_json_serialisable():
    """
    Agents return plain dicts, never BaseModel instances.

    model_dump(mode="json") is the conversion they rely on; if it stopped
    producing primitives, the API layer would fail at serialisation time.
    """
    import json

    assessment = RiskAssessment(**build_assessment())
    plan = ResponsePlan(**build_plan())

    json.dumps(assessment.model_dump(mode="json"))
    json.dumps(plan.model_dump(mode="json"))
