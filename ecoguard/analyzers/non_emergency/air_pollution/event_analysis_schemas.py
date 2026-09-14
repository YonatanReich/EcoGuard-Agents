"""Non-emergency Air Pollution Analyzer contracts.

These contracts begin after an external Coordinator has supplied routing and
identity.  They do not define, emulate, or persist a shared Coordinator.
"""

from __future__ import annotations

from datetime import timezone
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from ecoguard.detectors.air_pollution.schemas import AnomalyContract
from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import (
    AnalysisOrigin,
    TransportDataStatus,
    TransportEvidenceReference,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_prediction_service import (
    AirPollutionTransportPredictionExecution,
)
from ecoguard.shared.air_quality_schemas import MinistryAirQualityIndexEvidence

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
T = TypeVar("T")


class AnalysisComponent(AnomalyContract, Generic[T]):
    status: TransportDataStatus
    result: T | None = None
    evidence: list[TransportEvidenceReference] = Field(default_factory=list)
    limitations: list[Text] = Field(default_factory=list)
    unavailable_reason: Text | None = None

    @model_validator(mode="after")
    def _coherent_availability(self) -> "AnalysisComponent[T]":
        if self.status == "unavailable":
            if self.result is not None or self.unavailable_reason is None:
                raise ValueError("unavailable components require a reason and no result")
        elif self.result is None or not self.evidence or self.unavailable_reason is not None:
            raise ValueError("available components require result and evidence")
        if self.status == "partial" and not self.limitations:
            raise ValueError("partial components require limitations")
        identifiers = [item.evidence_id for item in self.evidence]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("component evidence IDs must be unique")
        return self


class CurrentPollutionState(AnomalyContract):
    derivation: Literal["coordinator_supplied_correlated_evidence"] = (
        "coordinator_supplied_correlated_evidence"
    )
    detections: list[PollutionCorrelationCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_detections(self) -> "CurrentPollutionState":
        identifiers = [item.anomaly.detection_id for item in self.detections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate detection IDs; grouping belongs to Coordinator")
        return self


class NonEmergencyRoutingMetadata(AnomalyContract):
    route: Literal["non_emergency"]
    routed_by: Text
    routed_at: AwareDatetime

    @field_validator("routed_at")
    @classmethod
    def _utc_time(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(timezone.utc)


class EventSeverityAssessment(AnomalyContract):
    """Source-native classification evidence, not an EcoGuard severity tier."""

    assessment_scope: Literal["event_level"] = "event_level"
    method: Literal["source_native_ministry_air_quality_index"] = (
        "source_native_ministry_air_quality_index"
    )
    ecoguard_severity_level: None = None
    ministry_index: MinistryAirQualityIndexEvidence
    five_minute_anomaly_evidence_is_separate: Literal[True] = True


class PollutantConcentrationPrediction(AnomalyContract):
    """Reserved trend-model result; this implementation leaves it unavailable."""

    pollutant: Text
    predicted_value: float
    unit: Text
    issued_at: AwareDatetime
    valid_at: AwareDatetime
    model_id: Text
    model_version: Text


class RelevantSettlementPopulationContext(AnomalyContract):
    """A corridor-relevant settlement reference, without invented population."""

    settlement_id: Text
    name: Text
    inside_transport_corridor: Literal[True] = True
    rank: int | None = Field(default=None, ge=1)
    population_status: Literal["unavailable"] = "unavailable"
    population: None = None
    unavailable_reason: Literal["authoritative_settlement_population_unavailable"] = (
        "authoritative_settlement_population_unavailable"
    )


class PopulationImpactContext(AnomalyContract):
    """Population geographically within a screening corridor, never exposure."""

    assessment_kind: Literal["geographically_relevant_population_screening"] = (
        "geographically_relevant_population_screening"
    )
    geometry_reference: Text
    query_method: Literal["area_weighted_population_grid_intersection"] = (
        "area_weighted_population_grid_intersection"
    )
    dataset_id: Text | None = None
    dataset_source: Text | None = None
    dataset_version: Text | None = None
    dataset_reference_year: int | None = Field(default=None, ge=1900, le=2200)
    queried_at: AwareDatetime
    intersected_cell_count: int = Field(ge=0)
    total_relevant_population: int = Field(ge=0)
    relevant_settlements: list[RelevantSettlementPopulationContext] = Field(
        default_factory=list
    )
    population_is_affected_count: Literal[False] = False
    exposure_not_confirmed: Literal[True] = True
    limitations: list[Text] = Field(min_length=1)

    @field_validator("queried_at")
    @classmethod
    def _population_time_to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _population_provenance_and_settlements(self):
        # The current shared table has no persisted dataset metadata.  Partial
        # metadata would be more misleading than an explicit all-null record.
        metadata = (
            self.dataset_id,
            self.dataset_source,
            self.dataset_version,
            self.dataset_reference_year,
        )
        if any(value is not None for value in metadata):
            raise ValueError("shared population dataset metadata is not available")
        identifiers = [item.settlement_id for item in self.relevant_settlements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("relevant settlement references must be unique")
        return self


class AirPollutionAnalysisInput(AnomalyContract):
    """Exact boundary supplied after external non-emergency routing."""

    incident_id: Text
    analysis_id: Text
    coordinator_routing_id: Text
    hazard_type: Literal["air_pollution"]
    requested_at: AwareDatetime
    routing: NonEmergencyRoutingMetadata
    analysis_origin: AnalysisOrigin
    evidence: list[TransportEvidenceReference] = Field(min_length=1)
    current_state: AnalysisComponent[CurrentPollutionState]

    @field_validator("requested_at")
    @classmethod
    def _utc_requested_at(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_external_boundary(self) -> "AirPollutionAnalysisInput":
        if self.routing.routed_at > self.requested_at:
            raise ValueError("routing cannot postdate analysis request")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("incident evidence IDs must be unique")
        if not set(self.analysis_origin.evidence_reference_ids).issubset(evidence_ids):
            raise ValueError("origin references must resolve to supplied evidence")
        state = self.current_state.result
        if state is not None:
            if any(item.anomaly.detected_at > self.requested_at for item in state.detections):
                raise ValueError("input detection cannot postdate analysis request")
            if (
                self.analysis_origin.analysis_origin_kind == "monitoring_location"
                and not any(
                    item.anomaly.location
                    == self.analysis_origin.analysis_origin_coordinates
                    for item in state.detections
                )
            ):
                raise ValueError("monitoring origin must match a supplied detection")
        return self


class AirPollutionEventAnalysis(AirPollutionAnalysisInput):
    generated_at: AwareDatetime
    status: TransportDataStatus
    severity_assessment: AnalysisComponent[EventSeverityAssessment]
    future_prediction: AnalysisComponent[PollutantConcentrationPrediction]
    transport_analysis: AnalysisComponent[AirPollutionTransportPredictionExecution]
    population_impact: AnalysisComponent[PopulationImpactContext]
    limitations: list[Text] = Field(min_length=1)
    exposure_not_confirmed: Literal[True] = True

    @field_validator("generated_at")
    @classmethod
    def _utc_generated_at(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _coherent_report(self) -> "AirPollutionEventAnalysis":
        if self.generated_at < self.requested_at:
            raise ValueError("analysis cannot be generated before requested_at")
        states = (
            self.current_state.status,
            self.severity_assessment.status,
            self.future_prediction.status,
            self.transport_analysis.status,
            self.population_impact.status,
        )
        expected = (
            "success"
            if all(status == "success" for status in states)
            else "unavailable"
            if all(status == "unavailable" for status in states)
            else "partial"
        )
        if self.status != expected:
            raise ValueError("report status must reflect component availability")
        transport = self.transport_analysis.result
        if transport is not None:
            if transport.analysis_origin != self.analysis_origin:
                raise ValueError("transport must use the supplied analysis origin")
            if transport.wind_evidence.requested_coordinates != self.analysis_origin.analysis_origin_coordinates:
                raise ValueError("wind evidence must use the supplied analysis origin")
            if transport.spatial_output.exposure_not_confirmed is not True:
                raise ValueError("transport output cannot confirm exposure")
        return self
