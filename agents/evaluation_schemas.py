"""
Evaluation Schemas

The shapes the judging agent must produce, and the arithmetic that turns them
into a score.

Separate from agents/risk_analysis_schemas.py on purpose: that module defines the
pipeline's own output contract, while this one belongs to the test instrument
that grades it. Keeping the graded and the grader apart means a change to one
cannot quietly alter the other.

There is no reference answer anywhere in this design. The judge holds a
hazard-indexed protocol corpus and decides whether a plan makes operational
sense given what the protocols say, using its own reading rather than a
similarity score against a model answer. Two plans that differ in wording but
agree in substance are supposed to receive identical scores.

Consumed by: agents.response_plan_judge_agent
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

DimensionName = Literal[
    "grounding",
    "unit_correctness",
    "action_quality",
    "proportionality",
    "safety_criticality",
]

# Safety carries the most weight because it is the only dimension whose failure
# mode injures someone. Unit correctness carries the least because naming a
# slightly wrong unit is a correctable clerical error, not a dangerous one.
DIMENSION_WEIGHTS: dict[str, float] = {
    "safety_criticality": 0.30,
    "proportionality": 0.20,
    "action_quality": 0.20,
    "grounding": 0.20,
    "unit_correctness": 0.10,
}

# A five-point ordinal with written anchors, not a 0-100 scale. Language models
# are unreliable at fine-grained numeric judgement and reliable at picking
# between a few clearly described bands, so the scale is kept where the
# judgement is actually sound.
MAX_DIMENSION_SCORE = 4


class DimensionScore(BaseModel):
    """
    One dimension's score, with the reasoning behind it.

    The rationale is required rather than optional because the per-dimension
    reasoning is the actual deliverable — a bare integer says the plan scored 2
    without saying what an engineer should change. Requiring prose alongside the
    number is also what makes the number worth reading.

    Attributes:
        dimension: Which dimension this scores.
        score: 0 to 4 against the anchors in the judge's system prompt.
        rationale: Why, specifically.
        evidence_chunk_ids: Protocol passages the judge is relying on. Ids not
            supplied to the judge are dropped and counted rather than failing
            the verdict — unlike the pipeline's citations, these are supporting
            detail rather than the basis of a life-safety instruction.
    """

    dimension: DimensionName
    score: int = Field(ge=0, le=MAX_DIMENSION_SCORE)
    rationale: str = Field(min_length=20, max_length=900)
    evidence_chunk_ids: list[str] = Field(default_factory=list, max_length=6)


class PlanVerdict(BaseModel):
    """
    The judge's assessment of one response plan.

    Attributes:
        verdict: Overall judgement. ``not_applicable`` covers the case where the
            pipeline produced no plan at all, which may be correct behaviour.
        dimensions: Exactly one entry per dimension, enforced below.
        corpus_coverage: Whether the corpus actually covers this scenario. This
            is what stops a plan being punished for failing to cite guidance
            that does not exist.
        strengths: What the plan got right.
        problems: What an operations officer would have to fix.
        missed_protocol_points: Relevant guidance the plan neither followed nor
            cited. This is what the judge's independent retrieval is for.
        summary: The verdict in prose.
    """

    verdict: Literal["sound", "sound_with_reservations", "unsound", "not_applicable"]
    dimensions: list[DimensionScore] = Field(min_length=5, max_length=5)

    @model_validator(mode="before")
    @classmethod
    def _drop_repeated_dimensions(cls, data):
        """
        Collapse a repeated dimension entry before the length check runs.

        Observed live: the judge occasionally emits six entries where one
        dimension appears twice. Only five dimensions exist, so a sixth entry is
        necessarily a duplicate and carries no new information — but a bare
        length constraint rejects the whole verdict for it, discarding a
        complete and useful evaluation over a formatting slip.

        This keeps the first occurrence of each dimension and drops later ones.
        It deliberately does not invent missing dimensions; a genuinely
        incomplete answer still fails, because that is a real defect rather than
        a slip.
        """
        if not isinstance(data, dict):
            return data

        dimensions = data.get("dimensions")
        if not isinstance(dimensions, list) or len(dimensions) <= 5:
            return data

        seen: set[str] = set()
        deduped = []

        for item in dimensions:
            name = (
                item.get("dimension") if isinstance(item, dict)
                else getattr(item, "dimension", None)
            )
            if name in seen:
                continue
            seen.add(name)
            deduped.append(item)

        return {**data, "dimensions": deduped}
    corpus_coverage: Literal[
        "covers_this_scenario", "partially_covers", "does_not_cover"
    ]
    strengths: list[str] = Field(default_factory=list, max_length=6)
    problems: list[str] = Field(default_factory=list, max_length=8)
    missed_protocol_points: list[str] = Field(default_factory=list, max_length=6)
    summary: str = Field(min_length=40, max_length=2000)

    @model_validator(mode="after")
    def _every_dimension_exactly_once(self) -> "PlanVerdict":
        """
        Require a complete, non-duplicated set of dimensions.

        An incomplete answer would otherwise be silently averaged over four
        dimensions and produce a score that looks comparable to a complete one
        but is not. Same technique as ResponsePlan._units_cover_actions: make
        the incoherent state impossible to express.

        Raises:
            ValueError: If any dimension is missing or repeated.
        """
        names = sorted(item.dimension for item in self.dimensions)
        expected = sorted(DIMENSION_WEIGHTS)

        if names != expected:
            missing = sorted(set(expected) - set(names))
            repeated = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(
                "dimensions must cover each of "
                f"{expected} exactly once; missing={missing} repeated={repeated}"
            )

        return self


def case_score(dimension_scores: dict[str, int]) -> float:
    """
    Combine dimension scores into one 0.0-1.0 figure.

    Args:
        dimension_scores (dict[str, int]): Score per dimension name.

    Returns:
        float: Weighted mean, normalised by the maximum, rounded to 3 places.
    """
    weighted = sum(
        DIMENSION_WEIGHTS[name] * score for name, score in dimension_scores.items()
    )

    return round(weighted / MAX_DIMENSION_SCORE, 3)
