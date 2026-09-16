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
from ecoguard.analyzers.non_emergency.air_pollution.event_analyzer import (
    AirPollutionNonEmergencyAnalyzer,
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
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._analyzer = analyzer
        self._planner = planner
        self._clock = clock

    def process(
        self,
        incident: Mapping[str, Any],
        context: IncidentDispatchContext,
    ) -> IncidentProcessingResult:
        if context.hazard != "air_pollution" or context.route != "non_emergency":
            raise ValueError("Air Pollution handler requires its advisory route")
        try:
            candidates = _pollution_candidates(incident)
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
            analysis = self._analyzer.analyze(analysis_input)
        except Exception as error:
            return self._failure(context, "analysis", error)

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


def _pollution_candidates(
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
    analyzer = AirPollutionNonEmergencyAnalyzer(
        transport_service=transport_service,
        ministry_index_client=MinistryAirQualityClient(),
        population_service=AirPollutionPopulationAnalysisService(),
        trend_inference_service=AirPollutionTrendInferenceService(),
    )
    return AirPollutionIncidentHandler(
        analyzer=analyzer,
        planner=AirPollutionResponsePlanner(),
    )
