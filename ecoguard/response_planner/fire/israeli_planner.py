"""The response planner: an incident report in, a grounded response plan out.

Takes what the fire analyser produced — the JSON and the narrative — retrieves
the procedures that bear on it, and produces a plan an emergency operator can
work down: what to do first, what to send, who to tell, who to move.

Retrieval is fixed, not agentic
-------------------------------
The build plan allows a bounded agent with three or four tool calls. This does
something stricter and cheaper: four *predetermined* filtered retrievals, then
one model call. The reasoning is the plan's own — "the plan varies run to run"
is not an acceptable property of a system that recommends dispatching emergency
vehicles — and a fixed retrieval takes that further than a capped loop does. It
is also about a third of the tokens, because nothing is retrieved twice and no
tool-call round trip carries the whole context again.

The four angles are the four questions a duty officer asks, and each is
filtered so it cannot be answered by the wrong doctrine:

    escalation   does this become a national event
    dispatch     how do I get more, and from where
    wildland     how is a settlement protected from an approaching fire
    interface    who else has to be involved

What is decided in code and what is asked of the model
------------------------------------------------------
Escalation is code: §2.1's criteria are thresholds with a stated source, and
`escalation.py` cites the clause rather than making the model re-derive it.
Station assignment is code: the allocator already ranks by road travel time.
Contact details are code: they come from the towns table and are passed in, so
the model never has the opportunity to invent a telephone number.

What is left for the model is the judgement-shaped part — what the response
should look like, in what order, and why — which is the only part retrieval
was ever for.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from ecoguard.response_planner.fire import escalation
from ecoguard.response_planner.fire.israeli_plan_schemas import (
    RESOURCE_TYPES,
    FireResponsePlan,
    PlannerResult,
    ProtocolCitation,
)
from ecoguard.response_planner.fire.dispatch import plan_dispatch
from ecoguard.response_planner.protocols.corpus_search import (
    search_protocols,
    verify_citations,
)
from ecoguard.shared.llm import ClaudeLLMService, ClaudeProviderError, build_system_blocks

logger = logging.getLogger(__name__)

AGENT_NAME = "IsraeliFireResponsePlanner"

# A full plan at the schema's maxima is comfortably over the service default of
# 4096, and the failure mode is not a helpful error — the response comes back
# as truncated JSON and fails validation as `json_invalid`, which reads like a
# model problem rather than a budget one. Sized with margin above the largest
# plan the schema now permits.
MAX_PLAN_TOKENS = 8192

# The four retrievals, as (label, query, filters). Fixed so two runs of the
# same incident see the same doctrine, and filtered so each question reaches
# only the documents that can answer it.
RETRIEVALS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "escalation",
        "אירוע ארצי סכנה ליישוב הסלמה דיווח למשלט הארצי",
        {"function": "escalation", "top_k": 3},
    ),
    (
        "dispatch",
        "סיוע בין מחוזי בקשת כוחות תגבור שיגור",
        {"function": "dispatch", "top_k": 3},
    ),
    (
        "wildland",
        "הגנה על יישוב מפני דליקת יער וחורש מתקרבת תכנית הגנה",
        {"hazard": "wildland", "top_k": 4},
    ),
    (
        "interface",
        'תיאום עם משטרה מד"א פיקוד העורף קק"ל פינוי אוכלוסייה',
        {"function": "interface", "top_k": 3},
    ),
)

# Enough of a chunk for the model to quote from, bounded so thirteen chunks
# cannot crowd out the incident they are about.
EXCERPT_CHARS = 900

SYSTEM = f"""\
You are the response planning component of EcoGuard, producing fire response
plans for emergency operations coordinators in Israel.

You receive an incident report from the fire analyser and excerpts from the
procedures of the Israeli Fire and Rescue Authority. You produce one response
plan.

## What is already decided, and must not be re-derived

- Whether this is a national event has been determined in code against
  הוראה 201 / 201.02.003 §2.1 and is given to you. Reason with it; it is
  recorded separately and you do not restate it as a field.
- The dispatch block — grade, responsible stations, team counts, police and
  MDA — is computed and given to you. Reference those stations by name in your
  actions. Never rename one, never change a team count, never add a station.
- Which settlements are exposed, how many people, and how long until the fire
  arrives are measured. Use those figures exactly; never adjust or round them.
- Contact details are supplied. Use only what you are given. Never invent a
  telephone number, a station name or an authority.

## What you decide

The shape of the response: what happens first, what to commit, who to tell,
who moves. Ground each of those in the excerpts supplied.

## Resource vocabulary

Use only these resource types. They are what an Israeli dispatcher assigns:

{chr(10).join(f"- {key} ({value})" for key, value in RESOURCE_TYPES.items())}

Never use international resource classes such as "Type 3 engine" or "hand
crew". They are unassignable here.

## Quantities

The Israeli dispatch guidance table (טבלת ההנחיה לשיגור) is NOT available to
you — it lives in the שלהבת CAD system and is not in this corpus. So:

- Give quantities you can justify from the incident's scale, and set
  `quantity_is_doctrinal: false` on every one of them.
- Set it true ONLY if a supplied excerpt states that quantity for this
  situation. It almost certainly does not.
- Add "no Israeli dispatch guidance table available; quantities are reasoned
  from incident scale" to coverage_gaps.

## Citations

Every citation must quote text that appears in the supplied excerpts, copied
exactly. Do not cite a procedure you were not shown. Do not paraphrase inside
quoted_text.

## Coverage gaps

State plainly what you could not ground. This corpus is strong on command,
coordination and escalation and thin on wildland suppression technique, water
supply and evacuation criteria. Where you recommend something the excerpts do
not cover, say so in coverage_gaps rather than implying doctrine exists.

Write for someone acting at 2am under time pressure. Be specific and short.
"""


def _excerpts(retrieved: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """The retrieved chunks, grouped by the question they were retrieved for."""
    blocks: list[str] = []
    for label, chunks in retrieved.items():
        if not chunks:
            blocks.append(f"### {label}\n(nothing in the corpus matched)")
            continue
        rendered = []
        for chunk in chunks:
            reference = chunk.get("procedure_number") or "(no procedure number)"
            clause = f" §{chunk['clause_path']}" if chunk.get("clause_path") else ""
            rendered.append(
                f"[{chunk['title']}] {reference}{clause}\n"
                f"{chunk['content'][:EXCERPT_CHARS]}"
            )
        blocks.append(f"### {label}\n" + "\n\n".join(rendered))
    return "\n\n".join(blocks)


def _incident_brief(
    analysis: Mapping[str, Any],
    services: Sequence[Mapping[str, Any]],
    national: Mapping[str, Any],
    dispatch: Mapping[str, Any] | None = None,
) -> str:
    """Everything the model needs about this incident, and nothing it does not.

    The analyser's own narrative is included whole: it is deterministic, every
    figure in it was computed, and rewriting it here would create a second
    account free to disagree with the first.
    """
    parts = [
        "## Incident report from the fire analyser",
        analysis.get("report") or "(no narrative)",
        "",
        "## National event determination (decided in code, cite as given)",
        national["statement"],
    ]
    if national["triggered"]:
        parts += [
            f"Triggered: " + "; ".join(
                f"§{item['clause']} {item['en']} — {item['evidence']}"
                for item in national["triggered"]
            )
        ]

    if dispatch and dispatch.get("status") == "ok":
        grade = dispatch.get("grade") or {}
        parts += [
            "",
            "## Dispatch (computed in code — do not restate or alter these)",
            f"Grade {grade.get('grade')} ({grade.get('teams_required')} teams): "
            f"{grade.get('reason')}",
            f"Responsible district: {dispatch.get('home_district')}",
        ]
        for station in dispatch.get("stations") or ():
            parts.append(
                f"- {station['teams']}x {station['name']} "
                f"[{station['district']}] under {station['request_type']} "
                f"({station['role']})"
            )
        if dispatch.get("teams_shortfall"):
            parts.append(
                f"SHORTFALL: {dispatch['teams_shortfall']} team(s) unfilled — "
                "say so in the plan."
            )
        for target in dispatch.get("police_notifications") or ():
            parts.append(
                f"- police for {target['locality']}: {target['police_station']}"
            )
        for target in dispatch.get("mda_notifications") or ():
            parts.append(
                f"- MDA for {target['locality']}: {target['mda_station']}"
            )

    if services:
        parts += ["", "## Responsible services, from the operational database",
                  "Use these names and numbers exactly. Do not invent others."]
        for entry in services:
            stations = ", ".join(
                station["name"] for station in entry.get("fire_stations", [])[:4]
            ) or "none on file"
            police = ", ".join(
                station["name"] for station in entry.get("police_stations", [])[:2]
            ) or "none on file"
            parts.append(
                f"- {entry.get('name')} (pop {entry.get('population')}): "
                f"fire district {entry.get('fire_district')}; "
                f"stations: {stations}; police: {police}; "
                f"authority {entry.get('authority')} "
                f"tel {entry.get('authority_phone') or 'not on file'}"
            )
    return "\n".join(parts)


def plan_response(
    analysis: Mapping[str, Any],
    *,
    services: Sequence[Mapping[str, Any]] = (),
    llm_service: ClaudeLLMService | None = None,
) -> PlannerResult:
    """Produce a grounded fire response plan from an analyser result.

    Args:
        analysis: a `spread_analyzer` result — the JSON and narrative together.
        services: `responsible_services` records for the exposed settlements,
            carrying station names and authority telephone numbers. Passed in
            rather than fetched so the model can only use real contacts and
            this function stays testable without a database.
        llm_service: injectable for tests.

    Returns:
        PlannerResult. A refusal is a result, not an exception: the hard gate
        below declines to plan for an analysis that made no assessment, because
        a plan built on a forecast that did not happen is the one fabrication
        an operator would act on.
    """
    incident_id = analysis.get("incident_id")

    if analysis.get("risk_semantics") != "fire_spread_forecast":
        return PlannerResult(
            status="skipped", incident_id=incident_id,
            error="not_a_fire_spread_analysis",
        )
    if analysis.get("status") != "ok":
        return PlannerResult(
            status="skipped", incident_id=incident_id,
            error=f"analysis_{analysis.get('status') or 'missing'}",
        )

    service = llm_service or ClaudeLLMService(
        effort="medium", max_tokens=MAX_PLAN_TOKENS
    )
    if not service.available:
        return PlannerResult(
            status="failed", incident_id=incident_id, error="missing_credentials",
        )

    national = escalation.assess(analysis)
    dispatch = plan_dispatch(analysis)

    retrieved: dict[str, list[dict[str, Any]]] = {}
    for label, query, filters in RETRIEVALS:
        try:
            retrieved[label] = search_protocols(query, **filters)
        except Exception:
            logger.exception("protocol retrieval failed for %s", label)
            retrieved[label] = []

    total = sum(len(chunks) for chunks in retrieved.values())
    if not total:
        return PlannerResult(
            status="failed", incident_id=incident_id,
            error="protocol_corpus_unavailable",
        )

    user_text = (
        f"{_incident_brief(analysis, services, national, dispatch)}\n\n"
        f"## Protocol excerpts — the only text you may cite\n\n"
        f"{_excerpts(retrieved)}"
    )

    try:
        plan = service.parse_structured(
            system_blocks=build_system_blocks(SYSTEM),
            user_text=user_text,
            output_format=FireResponsePlan,
        )
    except ClaudeProviderError as error:
        logger.error("planner model call failed: %s", error)
        return PlannerResult(
            status="failed", incident_id=incident_id, error=str(error),
            retrieved_chunks=total,
            # The computed blocks are unaffected by a model failure and are the
            # most actionable part of the answer. An operator whose plan failed
            # to generate should still be told the grade and which stations are
            # responsible, rather than nothing at all.
            escalation=dict(national), dispatch=dict(dispatch),
        )
    except ValidationError as error:
        logger.error("planner produced an invalid plan: %s", error)
        return PlannerResult(
            status="failed", incident_id=incident_id, error="invalid_plan",
            retrieved_chunks=total,
            escalation=dict(national), dispatch=dict(dispatch),
        )

    # Grounding is a property, not a request. Every citation is checked against
    # the text that was actually retrieved, and provenance is taken from the
    # matching chunk rather than from the model's self-report — so a correct
    # quotation attributed to the wrong procedure is corrected, and an invented
    # quotation cannot be rescued by naming a real one.
    all_chunks = [chunk for chunks in retrieved.values() for chunk in chunks]
    verified, dropped = verify_citations(
        [citation.model_dump() for citation in plan.protocol_citations],
        all_chunks,
    )
    if not verified:
        # The model answered but could not show its work against the text it
        # was given. Serving the plan anyway would present ungrounded
        # reasoning as protocol-derived, which is the thing this design exists
        # to refuse.
        logger.error("plan discarded: no citation verified (%s dropped)", dropped)
        return PlannerResult(
            status="failed", incident_id=incident_id, error="ungrounded_plan",
            retrieved_chunks=total, citations_dropped=dropped,
            escalation=dict(national), dispatch=dict(dispatch),
        )

    plan = plan.model_copy(update={
        "protocol_citations": [
            ProtocolCitation.model_validate(citation) for citation in verified
        ],
    })

    return PlannerResult(
        status="success",
        incident_id=incident_id,
        plan=plan,
        escalation=dict(national),
        dispatch=dict(dispatch),
        retrieved_chunks=total,
        citations_verified=len(verified),
        citations_dropped=dropped,
        model=service.model,
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
