"""
Risk Analysis Schemas

Responsible for the structured shapes the language model must produce, and for
deriving the operational risk band from a score.

This is the ONLY module in the project that defines Pydantic models, and that is
deliberate. The rest of the codebase passes plain dicts between agents, with the
shape documented in a Google-style ``Returns:`` block and pinned by tests. The
models here exist for one narrow job: validating a language model's answer at
the boundary where it enters the system. No BaseModel instance is allowed to
cross an agent's public boundary — the agents call ``model_dump(mode="json")``
and return plain dicts, and their tests assert ``json.dumps(result)`` succeeds.

Grounding is enforced structurally, not requested politely. ``protocol_citations``
has ``min_length=1`` on both output models, so an answer that cites nothing fails
validation before any code inspects it, and the agent reports "failed" rather
than passing an ungrounded assessment downstream.

A note on the tension in this design: Pydantic guarantees a value is *in range*,
while this repo's house rule is that failures must produce ``None`` rather than a
plausible default. Those pull in opposite directions. The resolution is that
these models are only ever constructed when the model actually answered. Every
failure path in the agents builds no model at all and reports ``risk_score:
None``. There is deliberately no ``default=50`` anywhere in this file.

Consumed by: agents.risk_analysis_agent, agents.response_planning_agent
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Closed vocabularies. Constraining these to enums means a validated response can
# never carry a unit id the frontend has no mapping for, so no defensive
# rendering is needed downstream.
UnitId = Literal[
    "fire_department",
    "police",
    "medical_services",
    "municipal_emergency_team",
    "home_front_command",
    "aerial_firefighting",
    "forestry_service",
    "utility_operator",
]

Timeframe = Literal["immediate", "within_1_hour", "within_6_hours", "ongoing"]

Confidence = Literal["low", "medium", "high"]

# Score bands, checked highest-first. Kept as data rather than an if-chain so the
# boundaries are visible in one place and directly parametrizable in tests.
RISK_LEVEL_BANDS: tuple[tuple[int, str], ...] = (
    (80, "critical"),
    (50, "high"),
    (25, "medium"),
    (0, "low"),
)


def risk_level_for_score(risk_score: int | None) -> str | None:
    """
    Map a 0-100 risk score onto its operational band.

    The band is derived in Python rather than asked of the model. Requesting
    both a score and a level invites incoherent pairs — a score of 82 labelled
    "medium" — and silently repairing that in a validator would itself be a form
    of fabrication. Deriving it removes the failure class entirely.

    Args:
        risk_score (int | None): Score from 0 to 100, or None when no assessment
            was produced.

    Returns:
        str | None: "critical", "high", "medium" or "low". None stays None —
            absence of a score is not evidence of low risk.
    """
    if risk_score is None:
        return None

    for threshold, level in RISK_LEVEL_BANDS:
        if risk_score >= threshold:
            return level

    return "low"


class ProtocolCitation(BaseModel):
    """
    One reference from the model back to a retrieved protocol chunk.

    Native document citations are unavailable here: the Anthropic API rejects
    ``citations: {enabled: true}`` together with structured outputs. So citations
    are schema fields the model self-reports, and are then verified in Python by
    ``services.protocol_retrieval_service.verify_citations`` against the chunk
    they name. The verification is the part that matters — a model can invent a
    convincing chunk id, which is precisely why the check exists.

    Attributes:
        chunk_id: Must be copied verbatim from a ``[chunk_id: ...]`` marker in
            the retrieved excerpts.
        document_title: The model's reading of the source. Overwritten from the
            retriever's own record during verification, so a real quote can
            never be misattributed.
        quoted_text: A verbatim span from that chunk. The 20-character floor
            stops a single word being offered as a citation.
        supports: Which part of the assessment this passage backs up.
    """

    chunk_id: str = Field(min_length=1, max_length=200)
    document_title: str = Field(min_length=1, max_length=200)
    # Both bounds are deliberately loose. Upper: a chunk can be 1200 characters
    # and quoting a long passage in full is correct behaviour. Lower: protocol
    # text includes table rows, and "Low | below 11.2" is a legitimate verbatim
    # citation of the FWI class table at 16 characters. A floor of 20 rejected
    # three assessments in four on a low-danger event — see the note at the
    # bottom of this module.
    quoted_text: str = Field(min_length=10, max_length=1400)
    supports: str = Field(min_length=1, max_length=500)

    @field_validator("chunk_id", "document_title", "quoted_text", "supports")
    @classmethod
    def _strip_whitespace(cls, value: str) -> str:
        """Trim surrounding whitespace so chunk ids compare cleanly."""
        return value.strip()


AreaType = Literal[
    "urban_dense",
    "urban_residential",
    "rural_settlement",
    "agricultural",
    "open_natural",
    "industrial",
    "wildland_urban_interface",
    "unknown",
]

PopulationBand = Literal[
    "none_nearby",
    "under_1k",
    "1k_to_10k",
    "10k_to_100k",
    "over_100k",
    "unknown",
]

# Ordered by how much weight a reader should give the number. An OSM tag is a
# recorded fact; a web lookup is a real source but one we did not collect
# ourselves; a settlement-type inference is a guess from "it is tagged as a
# village"; no_basis means we do not know.
PopulationBasis = Literal[
    "osm_population_tag",
    "web_search",
    "settlement_type_inference",
    "no_basis",
]

EvacuationConsideration = Literal[
    "not_indicated",
    "shelter_in_place_candidate",
    "localised_evacuation",
    "large_scale_evacuation",
    "unknown",
]


class WebFinding(BaseModel):
    """
    One fact the agent looked up because the collection layer did not supply it.

    Web findings are the only part of an assessment not derived from data we
    gathered ourselves, so each one carries its source and says which field it
    fills. ``services.claude_llm_service.verify_web_findings`` drops any whose
    host is off the allowlist before this reaches a caller: the API restricts
    what can be *read*, but the model is what *reports*, and a fabricated URL
    must not reach an operator.

    Attributes:
        query: What was searched for.
        fact: What was learned, in one sentence.
        source_url: Where it came from. Verified against the allowlist.
        source_title: The page or publication name.
        informs: Which part of the assessment this fills — the audit trail from
            a conclusion back to the lookup that supports it.
    """

    query: str = Field(min_length=3, max_length=300)
    fact: str = Field(min_length=10, max_length=600)
    source_url: str = Field(min_length=8, max_length=600)
    source_title: str = Field(min_length=1, max_length=300)
    informs: str = Field(min_length=3, max_length=300)


class SituationalContext(BaseModel):
    """
    What kind of place this is, and who is nearby.

    The response depends on this at least as much as on the fire itself: an
    identical hotspot warrants a different plan beside an apartment block than
    in open desert. The counts feeding these judgements are computed in Python
    (``build_situational_facts``); the model supplies only what needs judgement.

    Two anti-fabrication devices, both structural rather than requested:

    - ``area_type_basis`` is required **even when the type is "unknown"**. An
      unknown must say what it could not distinguish. This is the analogue of
      ``ProtocolCitation.supports``.
    - ``population_basis`` must name where a population figure came from, and
      the validator makes "no basis, but a confident band" impossible to
      express — the same technique as ``ResponsePlan._units_cover_actions``.

    Note that ``"unknown"`` is a member of each vocabulary rather than the field
    being optional. Inside an answer, not knowing must be an *active statement*;
    an optional field invites silent omission instead. The house rule that
    failures return ``None`` is satisfied by the agent's ``_build_empty`` path,
    which sets this whole block to ``None``.
    """

    area_type: AreaType
    area_type_basis: str = Field(min_length=20, max_length=600)
    population_band: PopulationBand
    population_basis: PopulationBasis
    evacuation_consideration: EvacuationConsideration
    context_gaps: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _population_band_requires_a_basis(self) -> "SituationalContext":
        """
        Reject a confident population band with nothing behind it.

        Raises:
            ValueError: If population_basis is "no_basis" but the band is not
                "unknown" — a figure asserted with no stated source.
        """
        if self.population_basis == "no_basis" and self.population_band != "unknown":
            raise ValueError(
                "population_band must be 'unknown' when population_basis is 'no_basis'"
            )
        return self


class RiskAssessment(BaseModel):
    """
    The model's structured judgement about a detected fire event.

    Note what is absent: there is no ``risk_level`` field (derived from the
    score by :func:`risk_level_for_score`), and no ``recommended_units`` or
    ``response_plan`` (those belong to the response planning agent). Keeping
    assessment and planning apart mirrors the separation the detection agent
    already maintains between satellite confidence, fire-weather severity and
    operational risk.

    Attributes:
        risk_score: Overall operational risk, 0-100.
        confidence: How much the evidence supports this score.
        primary_drivers: The specific signals that drove it, so a reviewer can
            check the reasoning against the evidence.
        explanation: Plain-language justification for an operator.
        situational_context: What kind of place this is and who is nearby. The
            response depends on this as much as on the fire itself.
        evidence_gaps: What the model could not determine. Populated when
            enrichment sources failed — this is how a degraded pipeline stays
            visible instead of being smoothed over.
        protocol_citations: At least one. An uncited assessment fails validation.
        web_findings: Facts looked up because the collection layer did not
            supply them. Empty on the ordinary path; every entry carries its
            source so a reader can tell a collected fact from a retrieved one.
    """

    risk_score: int = Field(ge=0, le=100)
    confidence: Confidence
    situational_context: SituationalContext
    primary_drivers: list[str] = Field(min_length=1, max_length=8)
    explanation: str = Field(min_length=40, max_length=3000)
    evidence_gaps: list[str] = Field(default_factory=list, max_length=8)
    protocol_citations: list[ProtocolCitation] = Field(min_length=1, max_length=8)
    web_findings: list[WebFinding] = Field(default_factory=list, max_length=6)


class ResponseAction(BaseModel):
    """
    One concrete action in a response plan.

    There is no ``order`` field: list position is the order. Asking for an
    integer index would only create duplicate and gap failure modes to validate
    away.

    Attributes:
        action: What to do, specifically enough to act on.
        responsible_unit: Which unit owns it. Constrained to the closed
            vocabulary.
        timeframe: How soon it must happen.
    """

    action: str = Field(min_length=10, max_length=600)
    responsible_unit: UnitId
    timeframe: Timeframe


class ResponsePlan(BaseModel):
    """
    The model's structured response plan for an assessed event.

    Attributes:
        recommended_units: Units to activate.
        actions: Ordered actions. Every action's unit must appear in
            ``recommended_units``.
        plan_summary: One-paragraph overview for the dashboard.
        assumptions: What the plan takes for granted, so an operator can check
            those before acting.
        protocol_citations: At least one. An uncited plan fails validation.
    """

    recommended_units: list[UnitId] = Field(min_length=1, max_length=8)
    actions: list[ResponseAction] = Field(min_length=1, max_length=16)
    plan_summary: str = Field(min_length=20, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    protocol_citations: list[ProtocolCitation] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _units_cover_actions(self) -> "ResponsePlan":
        """
        Reject a plan that assigns work to a unit it never recommended.

        Catches the classic incoherence: an action handed to
        ``aerial_firefighting`` while ``recommended_units`` omits it, leaving an
        operator with a task and nobody dispatched to do it.

        Raises:
            ValueError: If any action names a unit outside recommended_units.
        """
        assigned = {action.responsible_unit for action in self.actions}
        missing = assigned - set(self.recommended_units)

        if missing:
            raise ValueError(
                f"actions assigned to unrecommended units: {sorted(missing)}"
            )

        return self


# ---------------------------------------------------------------------------
# A note on the length limits above — read before tightening any of them.
#
# Their purpose is to bound runaway output, NOT to enforce brevity or to police
# quality. Brevity is a style instruction and belongs in the system prompt,
# where failing to follow it costs nothing. Quality is enforced by verifying
# citations against the corpus, which is a real check; a character count is not.
#
# This has now bitten twice, in both directions:
#
#   explanation  max_length=1200 rejected roughly one live answer in three.
#   quoted_text  min_length=20   rejected three in four on a low-danger event,
#                                because the model was correctly quoting a row
#                                of the FWI class table — "Low | below 11.2" is
#                                16 characters and is exactly the right
#                                citation for that event.
#
# Both failures are silent and expensive: the model is billed, the answer is
# correct and well-grounded, and the schema destroys it. In the second case the
# operator saw "malformed response" for a fire that had been assessed properly.
#
# The first versions of these limits were guesses, and they bound on real
# output. `explanation` was capped at 1200 characters; live runs produced 989,
# 1174 and 1290 characters for the same input, so roughly one call in three was
# rejected as "malformed response" and a perfectly good, well-cited assessment
# was thrown away. The score was discarded and the operator saw nothing.
#
# That failure mode is silent and expensive: the model is billed, the answer is
# correct, and the schema destroys it. A limit that trips on valid output is
# strictly worse than no limit at all.
#
# So each cap is now set well above anything observed:
#
#   field           observed        cap        purpose of the cap
#   explanation     ~1300 max       3000 max   stop a pathological essay
#   plan_summary    ~600 max        2000 max   same
#   action          ~200 max        600 max    same
#   quoted_text     16 min, ~250    10 min,    a table row is a valid citation;
#                                   1400 max   a chunk is at most ~1200 chars
#
# If you find yourself wanting shorter output, change the prompt, not these.
# If you find yourself wanting to reject weak citations, strengthen
# verify_citations, which checks the quote against the source text — that is
# evidence. A character count is not.
#
# When a schema rejection does happen, ClaudeLLMService.log_validation_detail
# logs the failing field names at WARNING, so the next instance of this is
# findable in one run rather than guessed at.
# ---------------------------------------------------------------------------
