"""Strict EA-312 decision-support contracts for air-pollution planning.

These records recommend authority and capability *types*. They never represent
availability, acceptance, allocation or dispatch. A successful recommendation
must be grounded in verified, pollution-specific guidance.
"""

from typing import Literal

from pydantic import Field, model_validator

from agents.air_pollution_anomaly_schemas import ContractModel
from agents.air_pollution_correlation import (
    PollutionCorrelationCandidate, PollutionCorrelationResult,
)
from agents.risk_analysis_schemas import ProtocolCitation

PlanningStatus = Literal["success", "failed", "skipped"]
PlanningReason = Literal[
    "insufficient_anomaly_evidence",
    "guidance_unavailable",
    "guidance_scope_mismatch",
    "correlation_context_mismatch",
    "model_unavailable",
    "model_failure",
    "malformed_output",
    "ungrounded_response",
]
AuthorityType = Literal[
    "environmental_protection_authority",
    "public_health_authority",
    "local_authority",
]
ResourceType = Literal[
    "air_quality_monitoring",
    "public_health_advisory",
    "public_information",
    "environmental_inspection",
    "laboratory_analysis",
]
ActionTimeframe = Literal["immediate", "within_1_hour", "within_6_hours", "ongoing", "not_specified"]
ActionPriority = Literal["urgent", "high", "routine", "monitoring", "not_specified"]


class AirPollutionRecommendedAction(ContractModel):
    """One recommendation, never a record that an action occurred."""

    recommendation: str = Field(min_length=10, max_length=600)
    responsible_authority_type: AuthorityType
    resource_type: ResourceType
    timeframe: ActionTimeframe
    priority: ActionPriority
    supporting_chunk_ids: list[str] = Field(min_length=1, max_length=6)


class AirPollutionPlanProposal(ContractModel):
    """Claude structured output before deterministic citation verification."""

    summary: str = Field(min_length=20, max_length=2000)
    recommended_authority_types: list[AuthorityType] = Field(min_length=1, max_length=3)
    recommended_resource_types: list[ResourceType] = Field(min_length=1, max_length=5)
    actions: list[AirPollutionRecommendedAction] = Field(min_length=1, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    evidence_gaps: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    protocol_citations: list[ProtocolCitation] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def actions_use_declared_types(self):
        authorities = {action.responsible_authority_type for action in self.actions}
        resources = {action.resource_type for action in self.actions}
        if not authorities.issubset(set(self.recommended_authority_types)):
            raise ValueError("actions use an authority type that was not recommended")
        if not resources.issubset(set(self.recommended_resource_types)):
            raise ValueError("actions use a resource type that was not recommended")
        return self


class VerifiedPollutionProtocolReference(ContractModel):
    chunk_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=200)
    document_title: str = Field(min_length=1, max_length=300)
    source_url: str = Field(min_length=8, max_length=1000)
    heading_path: str = Field(min_length=1, max_length=500)
    quoted_text: str = Field(min_length=10, max_length=1400)
    supports: str = Field(min_length=1, max_length=500)
    verified: Literal[True] = True


class AirPollutionResponsePlan(ContractModel):
    """Success or explicit safe failure; never an operational instruction."""

    status: PlanningStatus
    reason: PlanningReason | None = None
    summary: str | None = None
    recommended_authority_types: list[AuthorityType] = Field(default_factory=list)
    recommended_resource_types: list[ResourceType] = Field(default_factory=list)
    actions: list[AirPollutionRecommendedAction] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    protocol_references: list[VerifiedPollutionProtocolReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_is_coherent(self):
        if self.status == "success":
            if (
                self.reason is not None
                or not self.summary
                or not self.actions
                or not self.protocol_references
            ):
                raise ValueError("successful plans require actions and verified guidance")
        elif (
            self.reason is None or self.summary is not None or self.actions
            or self.recommended_authority_types or self.recommended_resource_types
            or self.protocol_references
        ):
            raise ValueError("non-success plans cannot contain operational-looking recommendations")
        return self


class AirPollutionPlanningResult(ContractModel):
    """Preserves the original event even when planning cannot proceed."""

    event: PollutionCorrelationCandidate
    correlation_evidence: PollutionCorrelationResult | None = None
    plan: AirPollutionResponsePlan
