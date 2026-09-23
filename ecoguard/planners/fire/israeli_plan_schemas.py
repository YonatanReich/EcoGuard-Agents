"""The shape of a fire response plan and the rules it must satisfy.

The validators here are the safety net: a plan whose status contradicts its
contents, or whose actions name units it never recommended, is rejected before
anyone sees it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The resources an Israeli fire dispatcher actually assigns, in the words the
# corpus uses. Latin keys so the rest of the system can branch on them; the
# Hebrew is what an operator reads.
RESOURCE_TYPES = {
    "fire_appliance": "כבאית",
    "water_tanker": "מכלית מים",
    "rapid_response_unit": 'יחידה לתגובה מהירה (יתמ)',
    "heavy_rescue": "רכב חילוץ",
    "aerial_firefighting": "מטוס כיבוי",
    "aerial_coordinator": "שדכן אווירי",
    "leviathan": "רכב לוויתן",
    "smoke_pusher": "דוחף עשן",
    "field_command": 'חפ"ק',
    "standby_squad": "כיתת כוננות יישובית",
    "police": "משטרת ישראל",
    "mda": 'מד"א',
    "home_front_command": 'פיקוד העורף (פקע"ר)',
    "kkl": 'קק"ל',
    "municipal_team": "צוות חירום רשותי",
    "idf_assistance": 'סיוע צה"ל',
}

ResourceType = Literal[tuple(RESOURCE_TYPES)]  # type: ignore[valid-type]

Timeframe = Literal["immediate", "within_30_minutes", "within_1_hour", "ongoing"]
Urgency = Literal["critical", "high", "routine"]


class PlanContract(BaseModel):
    """Strict base: a misspelled safety-critical field must never pass."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProtocolCitation(PlanContract):
    """Where a recommendation comes from, precisely enough to look up."""

    procedure_number: str | None = Field(
        default=None,
        description="e.g. 201.02.003, or the archival reference; null where "
                    "the document carries neither",
    )
    document_title: str = Field(min_length=3, max_length=300)
    clause_path: str | None = Field(default=None, description="e.g. 2.1.6")
    quoted_text: str = Field(
        min_length=8, max_length=400,
        description="the passage this rests on, copied from the excerpt",
    )
    supports: str = Field(
        min_length=8, max_length=300,
        description="which recommendation this passage supports",
    )

    # Filled by verification, not by the model. `division` and `publish_date`
    # come from the chunk whose text actually matched, so a citation carries
    # who issued the procedure and when — the second of which is what settles
    # precedence when one procedure supersedes another.
    division: str | None = Field(default=None, max_length=120)
    publish_date: str | None = Field(default=None, max_length=32)
    verified: bool = Field(
        default=False,
        description="true only after the quoted text was matched against the "
                    "retrieved chunk; a citation that reaches an operator "
                    "unverified is a claim rather than a source",
    )


class ResourceRequest(PlanContract):
    """What to send, in types the allocator can assign and a dispatcher knows."""

    resource_type: ResourceType
    quantity: int = Field(ge=1, le=40)
    urgency: Urgency
    rationale: str = Field(min_length=10, max_length=400)
    # The dispatch guidance table is not in the corpus. A quantity here is the
    # planner's reasoning, not a doctrinal requirement, and the flag says which
    # so a dispatcher knows whether to trust or to check.
    quantity_is_doctrinal: bool = Field(
        default=False,
        description="true only if a retrieved procedure states this quantity",
    )


class Notification(PlanContract):
    """Who to tell, and how. Contact details come from the store, not the model."""

    who: str = Field(min_length=2, max_length=160)
    why: str = Field(min_length=8, max_length=400)
    timeframe: Timeframe
    contact: str | None = Field(
        default=None, max_length=160,
        description="only if supplied in the incident data; never invented",
    )


class EvacuationDirective(PlanContract):
    """A settlement to move, and on what basis."""

    settlement: str = Field(min_length=1, max_length=160)
    action: Literal["evacuate_now", "prepare_to_evacuate", "shelter_and_standby"]
    population: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=8, max_length=400)
    responsible_authority: str | None = Field(default=None, max_length=160)
    authority_contact: str | None = Field(default=None, max_length=80)


class ResponseAction(PlanContract):
    """One ordered thing to do, with the authority behind it."""

    order: int = Field(ge=1, le=30)
    action: str = Field(min_length=12, max_length=400)
    responsible: str = Field(min_length=2, max_length=160)
    timeframe: Timeframe
    citation_index: int | None = Field(
        default=None, ge=0,
        description="index into protocol_citations; null where the action "
                    "follows from the incident data rather than from doctrine",
    )


class FireResponsePlan(PlanContract):
    """The plan an emergency operator reads and acts on."""

    situation_assessment: str = Field(min_length=40, max_length=1200)

    immediate_actions: list[ResponseAction] = Field(min_length=1, max_length=10)
    resource_requests: list[ResourceRequest] = Field(min_length=1, max_length=8)
    notifications: list[Notification] = Field(min_length=1, max_length=8)
    evacuation: list[EvacuationDirective] = Field(default_factory=list, max_length=12)

    protocol_citations: list[ProtocolCitation] = Field(min_length=1, max_length=8)
    coverage_gaps: list[str] = Field(
        min_length=1, max_length=10,
        description="what this plan could not ground in doctrine, stated "
                    "plainly rather than filled in",
    )
    assumptions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _citations_resolve(self) -> "FireResponsePlan":
        """An action citing a source must cite one that exists."""
        limit = len(self.protocol_citations)
        bad = [
            action.order for action in self.immediate_actions
            if action.citation_index is not None and action.citation_index >= limit
        ]
        if bad:
            raise ValueError(f"actions {bad} cite a citation index that does not exist")
        return self

    @model_validator(mode="after")
    def _actions_are_ordered(self) -> "FireResponsePlan":
        """Order is the sequence to work through, so it must be a sequence."""
        orders = [action.order for action in self.immediate_actions]
        if len(set(orders)) != len(orders):
            raise ValueError("two actions share the same order")
        return self


class PlannerResult(PlanContract):
    """The plan, the computed blocks beside it, and how it was produced.

    `plan` is what the model wrote. `escalation` and `dispatch` are what code
    computed and the model was given as input. They are separate fields rather
    than nested inside the plan because they have different authors and
    different trust: one is generated text with verified citations, the others
    are arithmetic over the store.
    """

    status: Literal["success", "failed", "skipped"]
    incident_id: str | None = None
    plan: FireResponsePlan | None = None

    # Computed in code, never generated. Typed loosely because both are
    # produced by modules that own their own shape and are already tested
    # there; re-declaring their fields here would be a second definition free
    # to drift from the first.
    escalation: dict[str, Any] | None = None
    dispatch: dict[str, Any] | None = None

    error: str | None = None
    retrieved_chunks: int = 0
    citations_verified: int = 0
    citations_dropped: int = 0
    model: str | None = None
    generated_at: str | None = None

    @model_validator(mode="after")
    def _status_is_coherent(self) -> "PlannerResult":
        """Reject a result whose status and plan disagree."""
        if self.status == "success" and self.plan is None:
            raise ValueError("a successful result must carry a plan")
        if self.status != "success" and self.plan is not None:
            raise ValueError("a failed or skipped result must not carry a plan")
        return self


def resource_label(resource_type: str) -> str:
    """The Hebrew an operator reads for a resource key."""
    return RESOURCE_TYPES.get(resource_type, resource_type)


def as_operator_text(
    plan: FireResponsePlan,
    *,
    escalation: dict[str, Any] | None = None,
    dispatch: dict[str, Any] | None = None,
) -> str:
    """The plan as the page a duty officer works down.

    Rendered here rather than asked of the model, so the ordering and the
    headings are the same on every incident and a reader who has seen one plan
    knows where to look in the next.
    """
    lines: list[str] = ["SITUATION", plan.situation_assessment, ""]

    if escalation and escalation.get("is_national"):
        lines += ["NATIONAL EVENT", escalation.get("statement", ""), ""]

    if dispatch and dispatch.get("status") == "ok":
        grade = dispatch.get("grade") or {}
        lines.append(
            f"DISPATCH — GRADE {grade.get('grade')} "
            f"({grade.get('teams_required')} teams)"
        )
        lines.append(f"  {grade.get('reason')}")
        lines.append(f"  responsible district: {dispatch.get('home_district')}")
        if dispatch.get("teams_shortfall"):
            lines.append(
                f"  SHORTFALL: {dispatch['teams_shortfall']} team(s) "
                "could not be filled from the stations on file"
            )
        for station in dispatch.get("stations") or ():
            marker = (
                "  <- parallel, no approval required"
                if str(station.get("role", "")).startswith("initial_response")
                else ""
            )
            lines.append(
                f"  {station['teams']}x {station['name']} "
                f"[{station['district']}] {station['request_type']}{marker}"
            )
        for target in dispatch.get("police_notifications") or ():
            lines.append(
                f"  police: {target['locality']} -> {target['police_station']}"
            )
        for target in dispatch.get("mda_notifications") or ():
            lines.append(
                f"  MDA: {target['locality']} -> {target['mda_station']} "
                f"({target['basis']})"
            )
        lines.append("")

    lines.append("IMMEDIATE ACTIONS")
    for action in sorted(plan.immediate_actions, key=lambda item: item.order):
        cite = ""
        if action.citation_index is not None:
            source = plan.protocol_citations[action.citation_index]
            reference = source.procedure_number or source.document_title[:40]
            cite = f"  [{reference}" + (
                f" §{source.clause_path}]" if source.clause_path else "]"
            )
        lines.append(
            f"  {action.order}. [{action.timeframe}] {action.action}"
            f"\n      responsible: {action.responsible}{cite}"
        )

    lines += ["", "RESOURCES TO COMMIT"]
    for request in plan.resource_requests:
        flag = "" if request.quantity_is_doctrinal else "  (reasoned, not doctrinal)"
        lines.append(
            f"  {request.quantity} x {resource_label(request.resource_type)}"
            f"  [{request.urgency}]{flag}\n      {request.rationale}"
        )

    lines += ["", "NOTIFY"]
    for note in plan.notifications:
        contact = f"  — {note.contact}" if note.contact else ""
        lines.append(f"  [{note.timeframe}] {note.who}{contact}\n      {note.why}")

    lines += ["", "EVACUATION"]
    if not plan.evacuation:
        lines.append("  No settlement requires evacuation on this assessment.")
    for item in plan.evacuation:
        contact = f" — {item.authority_contact}" if item.authority_contact else ""
        people = f", {item.population:,} residents" if item.population else ""
        lines.append(
            f"  [{item.action.replace('_', ' ').upper()}] {item.settlement}{people}"
            f"\n      {item.reason}"
            f"\n      authority: {item.responsible_authority or 'unknown'}{contact}"
        )

    lines += ["", "GROUNDED IN"]
    for index, citation in enumerate(plan.protocol_citations):
        reference = citation.procedure_number or "(no procedure number)"
        clause = f" §{citation.clause_path}" if citation.clause_path else ""
        lines.append(
            f"  [{index}] {citation.document_title[:70]} {reference}{clause}"
            f"\n      “{citation.quoted_text[:180]}”"
        )

    lines += ["", "NOT COVERED BY DOCTRINE"]
    lines += [f"  - {gap}" for gap in plan.coverage_gaps]

    if plan.assumptions:
        lines += ["", "ASSUMPTIONS"]
        lines += [f"  - {item}" for item in plan.assumptions]

    return "\n".join(lines)
