"""Typed contracts at the shared emergency planning boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ecoguard.shared.schemas import ProtocolCitation, Timeframe, UnitId

HazardType = Literal["fire", "flood", "earthquake"]
PlanningStatus = Literal["success", "failed", "skipped"]


class EmergencyContract(BaseModel):
    """Strict base so misspelled safety-critical fields never pass silently."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmergencyLocation(EmergencyContract):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class EmergencyResponsePlanInput(EmergencyContract):
    """Analyzer-agnostic handoff for one described emergency event."""

    hazard_type: HazardType
    event_description: str = Field(min_length=1, max_length=6000)
    incident_id: str | None = Field(default=None, min_length=1, max_length=200)
    location: EmergencyLocation | None = None
    risk_context: dict[str, Any] | None = None
    evidence_gaps: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=24)
    additional_context: dict[str, Any] = Field(default_factory=dict)


class EmergencyResponseAction(EmergencyContract):
    """An ordered action owned by a unit type, not a selected resource."""

    action: str = Field(min_length=10, max_length=600)
    responsible_unit: UnitId
    timeframe: Timeframe
    supporting_protocol_chunk_ids: list[str] = Field(min_length=1, max_length=8)


class EmergencyPlanProposal(EmergencyContract):
    """Structured Claude output before deterministic grounding verification."""

    recommended_units: list[UnitId] = Field(min_length=1, max_length=8)
    actions: list[EmergencyResponseAction] = Field(min_length=1, max_length=16)
    plan_summary: str = Field(min_length=20, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    protocol_citations: list[ProtocolCitation] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _units_cover_actions(self) -> "EmergencyPlanProposal":
        assigned = {action.responsible_unit for action in self.actions}
        missing = assigned - set(self.recommended_units)
        if missing:
            raise ValueError(f"actions assigned to unrecommended units: {sorted(missing)}")
        return self


class EmergencyPlanningMetadata(EmergencyContract):
    timestamp: str
    agent: str
    planning_status: PlanningStatus
    model: str | None = None
    reason: str | None = None


class EmergencyPlanGrounding(EmergencyContract):
    retriever: Literal["bm25"] = "bm25"
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    unverified_citation_count: int = Field(default=0, ge=0)


class EmergencyResponsePlan(EmergencyContract):
    """Grounded unit-type requirements, never allocation or dispatch."""

    metadata: EmergencyPlanningMetadata
    incident_id: str | None
    hazard_type: HazardType
    location: EmergencyLocation | None
    responding_to: dict[str, Any] | None = None
    plan_summary: str | None = None
    recommended_units: list[UnitId] = Field(default_factory=list)
    response_actions: list[EmergencyResponseAction] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    grounding: EmergencyPlanGrounding = Field(default_factory=EmergencyPlanGrounding)
    error: str | None = None

    @model_validator(mode="after")
    def _status_is_coherent(self) -> "EmergencyResponsePlan":
        if self.metadata.planning_status == "success":
            if (
                self.error is not None
                or not self.plan_summary
                or not self.recommended_units
                or not self.response_actions
                or not self.grounding.citations
            ):
                raise ValueError("successful plans require grounded recommendations")
        elif self.recommended_units or self.response_actions or self.plan_summary is not None:
            raise ValueError("non-success plans cannot contain recommendations")
        return self
