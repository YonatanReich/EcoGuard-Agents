"""Compose non-emergency Air Pollution analysis from existing science services."""

from collections.abc import Callable
from datetime import datetime, timezone

from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.analyzers.non_emergency.air_pollution.event_analysis_schemas import (
    AirPollutionAnalysisInput,
    AirPollutionEventAnalysis,
    AirPollutionTrendPrediction,
    AnalysisComponent,
    EventSeverityAssessment,
    PopulationImpactContext,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import TransportEvidenceReference
from ecoguard.analyzers.non_emergency.air_pollution.transport_prediction_service import (
    AirPollutionTransportPredictionExecution,
    AirPollutionTransportPredictionService,
)
from ecoguard.analyzers.non_emergency.air_pollution.population_analysis import (
    AirPollutionPopulationAnalysisService,
)
from ecoguard.shared.ministry_air_quality_client import MinistryAirQualityClient
from ecoguard.analyzers.non_emergency.air_pollution.trend_inference_service import (
    AirPollutionTrendInferenceService,
)

ANALYZER_LIMITATIONS = [
    "Transport output is deterministic screening, not proof of pollutant transport or exposure.",
    "The monitoring location is not assumed to be an emission source.",
    "Ministry index evidence is source-native context, not an EcoGuard LOW/MEDIUM/HIGH severity tier.",
]


class AirPollutionNonEmergencyAnalyzer:
    """Analyze externally routed evidence; never detect, route, persist, or plan."""

    def __init__(
        self,
        *,
        transport_service: AirPollutionTransportPredictionService | None,
        ministry_index_client: MinistryAirQualityClient | None = None,
        population_service: AirPollutionPopulationAnalysisService | None = None,
        trend_inference_service: AirPollutionTrendInferenceService | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._transport_service = transport_service
        self._ministry_index_client = ministry_index_client
        self._population_service = population_service
        self._trend_inference_service = trend_inference_service
        self._clock = clock

    def analyze(self, analysis_input: AirPollutionAnalysisInput) -> AirPollutionEventAnalysis:
        validated = AirPollutionAnalysisInput.model_validate(
            analysis_input.model_dump(round_trip=True)
        )
        generated_at = self._clock()
        if generated_at.utcoffset() is None:
            raise ValueError("analyzer clock must be timezone-aware")
        generated_at = generated_at.astimezone(timezone.utc)
        transport = self._transport_component(validated)
        population = self._population_component(validated, transport, generated_at)
        severity = self._severity_component(validated)
        prediction = self._trend_component(validated)
        component_statuses = (
            validated.current_state.status,
            severity.status,
            prediction.status,
            transport.status,
            population.status,
        )
        status = (
            "success"
            if all(value == "success" for value in component_statuses)
            else "unavailable"
            if all(value == "unavailable" for value in component_statuses)
            else "partial"
        )
        return AirPollutionEventAnalysis(
            **validated.model_dump(round_trip=True),
            generated_at=generated_at,
            status=status,
            severity_assessment=severity,
            future_prediction=prediction,
            transport_analysis=transport,
            population_impact=population,
            limitations=list(dict.fromkeys([*ANALYZER_LIMITATIONS, *population.limitations])),
        )

    def _trend_component(
        self, analysis_input: AirPollutionAnalysisInput
    ) -> AnalysisComponent[AirPollutionTrendPrediction]:
        if self._trend_inference_service is None:
            return AnalysisComponent[AirPollutionTrendPrediction](
                status="unavailable",
                unavailable_reason="trend_inference_service_unavailable",
            )
        matches = self._origin_candidates(analysis_input)
        if not matches:
            return AnalysisComponent[AirPollutionTrendPrediction](
                status="unavailable",
                unavailable_reason="analysis_origin_detection_unavailable",
            )
        if len(matches) != 1:
            return AnalysisComponent[AirPollutionTrendPrediction](
                status="unavailable",
                unavailable_reason="ambiguous_origin_series",
            )
        try:
            return self._trend_inference_service.predict(matches[0])
        except Exception:
            return AnalysisComponent[AirPollutionTrendPrediction](
                status="unavailable",
                unavailable_reason="trend_inference_failure",
            )

    def _population_component(
        self,
        analysis_input: AirPollutionAnalysisInput,
        transport: AnalysisComponent[AirPollutionTransportPredictionExecution],
        queried_at: datetime,
    ) -> AnalysisComponent[PopulationImpactContext]:
        if self._population_service is None:
            return AnalysisComponent[PopulationImpactContext](
                status="unavailable",
                unavailable_reason="shared_population_service_unavailable",
            )
        if transport.result is None:
            return AnalysisComponent[PopulationImpactContext](
                status="unavailable",
                unavailable_reason="transport_corridor_unavailable",
            )
        try:
            return self._population_service.analyze(
                transport.result.spatial_output,
                geometry_reference=f"air-pollution-transport:{analysis_input.analysis_id}:corridor",
                evidence_id=f"population-grid:{analysis_input.analysis_id}",
                queried_at=queried_at,
            )
        except Exception:
            return AnalysisComponent[PopulationImpactContext](
                status="unavailable",
                unavailable_reason="shared_population_analysis_failed",
            )

    def _severity_component(
        self, analysis_input: AirPollutionAnalysisInput
    ) -> AnalysisComponent[EventSeverityAssessment]:
        if self._ministry_index_client is None:
            return AnalysisComponent[EventSeverityAssessment](
                status="unavailable",
                unavailable_reason="ministry_air_quality_index_service_unavailable",
            )
        candidate = self._origin_candidate(analysis_input)
        if candidate is None:
            return AnalysisComponent[EventSeverityAssessment](
                status="unavailable",
                unavailable_reason="analysis_origin_detection_unavailable",
            )
        anomaly = candidate.anomaly
        try:
            lookup = self._ministry_index_client.get_station_index_evidence(
                station_id=anomaly.station_id,
                channel_id=anomaly.channel_id,
                pollutant=anomaly.pollutant,
                observed_at=anomaly.observed_at,
            )
        except Exception:
            return AnalysisComponent[EventSeverityAssessment](
                status="unavailable",
                unavailable_reason="ministry_air_quality_index_lookup_unavailable",
            )
        if lookup.status != "available" or lookup.evidence is None:
            return AnalysisComponent[EventSeverityAssessment](
                status="unavailable",
                unavailable_reason=lookup.reason or "ministry_air_quality_index_unavailable",
            )
        index = lookup.evidence
        if (
            index.station_id,
            index.resolved_channel_id,
            index.pollutant,
        ) != (anomaly.station_id, anomaly.channel_id, anomaly.pollutant):
            return AnalysisComponent[EventSeverityAssessment](
                status="unavailable",
                unavailable_reason="ministry_air_quality_index_identity_mismatch",
            )
        evidence = TransportEvidenceReference(
            evidence_id=index.evidence_id,
            source_name=index.source,
            source_type=index.classification_system,
            reference=index.source_endpoint,
            metadata={
                "station_id": index.station_id,
                "monitor_id": index.monitor_id,
                "pollutant": index.pollutant,
                "provider_timestamp": index.provider_timestamp.isoformat(),
                "averaging_period_minutes": index.averaging_period_minutes,
                "preliminary": index.preliminary,
            },
        )
        return AnalysisComponent[EventSeverityAssessment](
            status="partial",
            result=EventSeverityAssessment(ministry_index=index),
            evidence=[evidence],
            limitations=list(index.limitations),
        )

    def _transport_component(
        self, analysis_input: AirPollutionAnalysisInput
    ) -> AnalysisComponent[AirPollutionTransportPredictionExecution]:
        if self._transport_service is None:
            return AnalysisComponent[AirPollutionTransportPredictionExecution](
                status="unavailable",
                unavailable_reason="wind_or_transport_service_unavailable",
                limitations=["No wind-backed transport screening was performed."],
            )
        if analysis_input.analysis_origin.analysis_origin_kind != "monitoring_location":
            return AnalysisComponent[AirPollutionTransportPredictionExecution](
                status="unavailable",
                unavailable_reason="analysis_origin_not_supported_by_transport_service",
                limitations=["Current transport screening supports monitoring-location origins only."],
            )
        candidate = self._origin_candidate(analysis_input)
        if candidate is None:
            return AnalysisComponent[AirPollutionTransportPredictionExecution](
                status="unavailable",
                unavailable_reason="analysis_origin_detection_unavailable",
            )
        try:
            result = self._transport_service.predict(
                candidate, analysis_origin=analysis_input.analysis_origin
            )
        except Exception:
            return AnalysisComponent[AirPollutionTransportPredictionExecution](
                status="unavailable",
                unavailable_reason="wind_evidence_or_transport_screening_unavailable",
                limitations=["Provider or scientific screening did not return usable evidence."],
            )
        if result.analysis_origin != analysis_input.analysis_origin:
            return AnalysisComponent[AirPollutionTransportPredictionExecution](
                status="unavailable",
                unavailable_reason="transport_origin_mismatch",
            )
        evidence = self._transport_evidence(analysis_input, result)
        spatial = result.spatial_output
        return AnalysisComponent[AirPollutionTransportPredictionExecution](
            status=spatial.data_status,
            result=result,
            evidence=evidence,
            limitations=list(spatial.limitations) if spatial.data_status == "partial" else [],
        )

    @staticmethod
    def _origin_candidate(
        analysis_input: AirPollutionAnalysisInput,
    ) -> PollutionCorrelationCandidate | None:
        matches = AirPollutionNonEmergencyAnalyzer._origin_candidates(analysis_input)
        return matches[0] if matches else None

    @staticmethod
    def _origin_candidates(
        analysis_input: AirPollutionAnalysisInput,
    ) -> list[PollutionCorrelationCandidate]:
        state = analysis_input.current_state.result
        if state is None:
            return []
        referenced_ids = set(
            analysis_input.analysis_origin.evidence_reference_ids
        )
        referenced = [
            item
            for item in state.detections
            if item.anomaly.detection_id in referenced_ids
        ]
        if referenced:
            return referenced
        origin = analysis_input.analysis_origin.analysis_origin_coordinates
        return [
            item for item in state.detections if item.anomaly.location == origin
        ]

    @staticmethod
    def _transport_evidence(
        analysis_input: AirPollutionAnalysisInput,
        result: AirPollutionTransportPredictionExecution,
    ) -> list[TransportEvidenceReference]:
        evidence = list(analysis_input.evidence)
        wind = result.wind_evidence
        if wind.evidence_id not in {item.evidence_id for item in evidence}:
            evidence.append(
                TransportEvidenceReference(
                    evidence_id=wind.evidence_id,
                    source_name=wind.provider,
                    source_type=wind.source_type,
                    reference=wind.reference,
                    metadata={
                        "provider_location_id": wind.provider_location_id,
                        "provider_validity": wind.provider_validity,
                        "effective_at": wind.effective_at.isoformat(),
                    },
                )
            )
        return evidence
