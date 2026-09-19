"""Air Pollution implementation of the shared incident dispatch contract."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from ecoguard.analyzers.non_emergency.air_pollution.analysis_adapter import (
    adapt_non_emergency_air_pollution_analysis_input,
)
from ecoguard.analyzers.non_emergency.air_pollution.additional_verification import (
    AirPollutionAdditionalVerificationService,
)
from ecoguard.analyzers.non_emergency.air_pollution.event_qualification import (
    MatchingOfficialPollutantIndex,
    ProjectedAirPollutionIdentity,
    qualify_air_pollution_event,
)
from ecoguard.analyzers.non_emergency.air_pollution.event_analyzer import (
    AirPollutionNonEmergencyAnalyzer,
)
from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import (
    AirPollutionEventAnalysis,
)
from ecoguard.analyzers.non_emergency.air_pollution.official_classification import (
    classify_official_pollutant_sub_index,
    publication_policy,
)
from ecoguard.analyzers.non_emergency.air_pollution.population_analysis import (
    AirPollutionPopulationAnalysisService,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_prediction_service import (
    configured_air_pollution_transport_prediction_service,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import (
    AnalysisOrigin,
    TransportEvidenceReference,
)
from ecoguard.analyzers.non_emergency.air_pollution.trend_inference_service import (
    AirPollutionTrendInferenceService,
)
from ecoguard.coordinator.dispatcher import (
    IncidentDispatchContext,
    IncidentProcessingResult,
)
from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.detectors.air_pollution.spatial_enrichment import (
    AirPollutionSpatialEnricher,
)
from ecoguard.response_planner.air_pollution.planner import AirPollutionResponsePlanner
from ecoguard.shared.ministry_air_quality_client import MinistryAirQualityClient

logger = logging.getLogger(__name__)


class AirPollutionIncidentEvidenceError(ValueError):
    """The incident has no honest, validated Air Pollution analyzer evidence."""


class AirPollutionIncidentHandler:
    """Rehydrate preserved evidence, analyze it, then invoke the existing planner."""

    name = "air_pollution_non_emergency_analysis_planning"

    def __init__(
        self,
        *,
        analyzer: AirPollutionNonEmergencyAnalyzer,
        planner: AirPollutionResponsePlanner,
        verification_service: AirPollutionAdditionalVerificationService | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._analyzer = analyzer
        self._planner = planner
        self._verification_service = (
            verification_service or AirPollutionAdditionalVerificationService()
        )
        self._clock = clock

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult:
        if context.hazard != "air_pollution" or context.route != "non_emergency":
            raise ValueError("Air Pollution handler requires its advisory route")
        try:
            candidates = pollution_candidates_from_incident(incident)
            latest = max(candidates, key=lambda item: item.anomaly.observed_at)
            evidence = [_candidate_reference(item) for item in candidates]
            origin_reference = _candidate_reference(latest).evidence_id
            analysis_input = adapt_non_emergency_air_pollution_analysis_input(
                incident_id=context.incident_id,
                analysis_id=context.analysis_id,
                coordinator_routing_id=context.coordinator_routing_id,
                route=context.route,
                routed_by=context.routed_by,
                routed_at=context.routed_at,
                requested_at=context.requested_at,
                analysis_origin=AnalysisOrigin(
                    analysis_origin_kind="monitoring_location",
                    analysis_origin_coordinates=latest.anomaly.location,
                    evidence_reference_ids=[origin_reference],
                ),
                correlated_detections=candidates,
                evidence=evidence,
            )
        except Exception as error:
            return self._failure(context, "adaptation", error)

        try:
            severity = self._analyzer.assess_official_index(analysis_input)
            qualification, classification, policy = self._ea371_decision(
                incident=incident,
                latest=latest,
                severity=severity,
            )
            analysis = self._analyzer.analyze(
                analysis_input,
                severity_assessment=severity,
                run_heavy_analysis=policy.publish_to_operational_dashboard,
            )
        except Exception as error:
            return self._failure(context, "analysis", error)

        if isinstance(analysis, AirPollutionEventAnalysis):
            analysis = self._apply_ea371_policy(
                incident=incident,
                analysis=analysis,
                qualification=qualification,
                classification=classification,
                policy=policy,
            )

        try:
            planning = self._planner.plan_response(analysis)
        except Exception as error:
            return self._failure(
                context,
                "planning",
                error,
                analysis_status=analysis.status,
                analysis_result=analysis,
            )

        status = (
            "success"
            if analysis.status == "success" and planning.plan.status == "success"
            else "partial"
        )
        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status=status,
            requested_at=context.requested_at,
            completed_at=self._now(),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
            analysis_status=analysis.status,
            planner_status=planning.plan.status,
            analysis_result=analysis,
            planner_result=planning,
        )

    def _apply_ea371_policy(
        self,
        *,
        incident: Mapping[str, Any],
        analysis: AirPollutionEventAnalysis,
        qualification,
        classification,
        policy,
    ) -> AirPollutionEventAnalysis:
        verification = self._verification_service.verify(
            incident=incident,
            analysis=analysis,
            qualification=qualification,
            classification=classification,
            checked_at=self._now(),
        )
        analysis = analysis.model_copy(update={
            "event_qualification": qualification,
            "official_pollutant_classification": classification,
            "publication_policy": policy,
            "additional_verification": verification,
        })
        return AirPollutionEventAnalysis.model_validate(
            analysis.model_dump(round_trip=True)
        )

    @staticmethod
    def _ea371_decision(
        *,
        incident: Mapping[str, Any],
        latest: PollutionCorrelationCandidate,
        severity,
    ):
        ministry = (
            severity.result.ministry_index
            if severity.result is not None
            else None
        )
        official_index = (
            MatchingOfficialPollutantIndex(
                station_id=ministry.station_id,
                channel_id=ministry.resolved_channel_id,
                pollutant=ministry.pollutant,
                pollutant_sub_index=ministry.pollutant_sub_index,
            )
            if ministry is not None
            else None
        )
        projected = ProjectedAirPollutionIdentity(
            station_id=latest.anomaly.station_id,
            channel_id=latest.anomaly.channel_id,
            pollutant=latest.anomaly.pollutant,
            observed_at=latest.anomaly.observed_at,
            provider=latest.anomaly.provider,
        )
        qualification = qualify_air_pollution_event(
            incident,
            projected=projected,
            official_index=official_index,
        )
        classification = classify_official_pollutant_sub_index(
            pollutant=latest.anomaly.pollutant,
            pollutant_sub_index=(
                ministry.pollutant_sub_index
                if ministry is not None
                and ministry.station_id == latest.anomaly.station_id
                and ministry.resolved_channel_id == latest.anomaly.channel_id
                and ministry.pollutant == latest.anomaly.pollutant
                else None
            ),
        )
        policy = publication_policy(qualification, classification)
        return qualification, classification, policy

    def _failure(
        self,
        context: IncidentDispatchContext,
        stage: str,
        error: Exception,
        *,
        analysis_status: str | None = None,
        analysis_result: Any | None = None,
    ) -> IncidentProcessingResult:
        logger.exception(
            "Air Pollution incident %s failed during %s",
            context.incident_id,
            stage,
            exc_info=error,
        )
        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status="failed",
            requested_at=context.requested_at,
            completed_at=self._now(),
            analysis_id=context.analysis_id,
            coordinator_routing_id=context.coordinator_routing_id,
            handler=self.name,
            analysis_status=analysis_status,
            analysis_result=analysis_result,
            failure_stage=stage,
            failure_reason=(
                str(error)
                if isinstance(error, AirPollutionIncidentEvidenceError)
                else type(error).__name__
            ),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("handler clock must carry a UTC offset")
        return value.astimezone(timezone.utc)


def pollution_candidates_from_incident(
    incident: Mapping[str, Any],
) -> list[PollutionCorrelationCandidate]:
    """Read only candidates preserved by Air Pollution CellSignals."""

    candidates: dict[str, PollutionCorrelationCandidate] = {}
    for signal in incident.get("signals") or ():
        if not isinstance(signal, Mapping) or signal.get("hazard") != "air_pollution":
            continue
        evidence = signal.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        payload = evidence.get("correlation_candidate")
        if not isinstance(payload, Mapping):
            continue
        try:
            # JSON persistence includes Pydantic computed fields for audit and
            # display. Rehydrate only the declared input fields; the model
            # recomputes hazard/category/reference views from the anomaly.
            candidate = PollutionCorrelationCandidate.model_validate({
                field: payload[field]
                for field in PollutionCorrelationCandidate.model_fields
                if field in payload
            })
        except (TypeError, ValueError):
            continue
        candidates.setdefault(candidate.anomaly.detection_id, candidate)
    if not candidates:
        raise AirPollutionIncidentEvidenceError(
            "air_pollution_correlation_evidence_unavailable"
        )
    return sorted(candidates.values(), key=lambda item: item.anomaly.observed_at)


def _candidate_reference(
    candidate: PollutionCorrelationCandidate,
) -> TransportEvidenceReference:
    anomaly = candidate.anomaly
    baseline = anomaly.baseline_evidence
    return TransportEvidenceReference(
        evidence_id=anomaly.detection_id,
        source_name=anomaly.provider,
        source_type="persisted_coordinator_cell_signal",
        reference=baseline.version.content_sha256,
        metadata={
            "station_id": anomaly.station_id,
            "channel_id": anomaly.channel_id,
            "pollutant": anomaly.pollutant,
            "unit": anomaly.unit,
            "observed_at": anomaly.observed_at.isoformat(),
            "baseline_p95": baseline.statistics.p95,
            "p95_is_health_or_severity_threshold": False,
            "monitoring_location_is_emission_source": False,
        },
    )


@lru_cache(maxsize=1)
def configured_air_pollution_incident_handler() -> AirPollutionIncidentHandler:
    """Build the production stack once; individual components fail gracefully."""

    try:
        transport_service = configured_air_pollution_transport_prediction_service()
    except Exception:
        logger.exception("Air Pollution transport composition unavailable")
        transport_service = None
    ministry_client = MinistryAirQualityClient()
    analyzer = AirPollutionNonEmergencyAnalyzer(
        transport_service=transport_service,
        ministry_index_client=ministry_client,
        population_service=AirPollutionPopulationAnalysisService(),
        trend_inference_service=AirPollutionTrendInferenceService(),
        spatial_enricher=AirPollutionSpatialEnricher(),
    )
    return AirPollutionIncidentHandler(
        analyzer=analyzer,
        planner=AirPollutionResponsePlanner(),
        verification_service=AirPollutionAdditionalVerificationService(),
    )
