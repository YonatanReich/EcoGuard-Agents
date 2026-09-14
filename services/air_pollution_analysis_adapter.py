"""Pure adapter from externally routed correlation evidence to analyzer input."""

from collections.abc import Sequence
from datetime import datetime

from agents.air_pollution_correlation import PollutionCorrelationCandidate
from agents.air_pollution_event_analysis_schemas import (
    AirPollutionAnalysisInput,
    AnalysisComponent,
    CurrentPollutionState,
    NonEmergencyRoutingMetadata,
)
from agents.air_pollution_transport_schemas import (
    AnalysisOrigin,
    TransportEvidenceReference,
)


def adapt_non_emergency_air_pollution_analysis_input(
    *,
    incident_id: str,
    analysis_id: str,
    coordinator_routing_id: str,
    route: str,
    routed_by: str,
    routed_at: datetime,
    requested_at: datetime,
    analysis_origin: AnalysisOrigin,
    correlated_detections: Sequence[PollutionCorrelationCandidate],
    evidence: Sequence[TransportEvidenceReference],
) -> AirPollutionAnalysisInput:
    """Validate Coordinator-owned values without generating or persisting them."""

    if route != "non_emergency":
        raise ValueError("Air Pollution Analyzer requires external non_emergency routing")
    detections = [
        PollutionCorrelationCandidate.model_validate(item.model_dump(round_trip=True))
        for item in correlated_detections
    ]
    references = [
        TransportEvidenceReference.model_validate(item.model_dump()) for item in evidence
    ]
    return AirPollutionAnalysisInput(
        incident_id=incident_id,
        analysis_id=analysis_id,
        coordinator_routing_id=coordinator_routing_id,
        hazard_type="air_pollution",
        requested_at=requested_at,
        routing=NonEmergencyRoutingMetadata(
            route=route,
            routed_by=routed_by,
            routed_at=routed_at,
        ),
        analysis_origin=analysis_origin,
        evidence=references,
        current_state=AnalysisComponent[CurrentPollutionState](
            status="success",
            result=CurrentPollutionState(detections=detections),
            evidence=references,
        ),
    )
