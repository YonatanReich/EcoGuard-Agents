"""Map processing results to durable frontend-compatible SharedEvents."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ecoguard.analyzers.air_pollution.incident_handler import (
    pollution_candidates_from_incident,
)
from ecoguard.analyzers.flood.event_analysis_schemas import (
    FloodEventAnalysis,
)
from ecoguard.analyzers.flood.risk_analysis_schemas import (
    FloodRiskAssessment,
)
from ecoguard.coordinator import incidents as incident_store
from ecoguard.coordinator.dispatcher import IncidentProcessingResult
from ecoguard.database.repositories.event_projections import (
    EventProjectionWrite,
    event_projection_by_incident,
    upsert_event_projection,
)
from ecoguard.shared.events import (
    AirPollutionAdditionalVerification,
    AirPollutionBaselineContext,
    AirPollutionDetails,
    AirPollutionRecommendation,
    AirPollutionSettlement,
    AirPollutionSettlementContext,
    AirPollutionSharedEvent,
    AirPollutionPublicationPolicy,
    AirPollutionStation,
    AirPollutionTransportScreening,
    AirPollutionWindEvidence,
    ComponentUnavailableReason,
    CorridorPopulationContext,
    EarthquakeDetails,
    EarthquakePopulationSummary,
    EarthquakeSharedEvent,
    EarthquakeTown,
    GeoJsonLineString,
    GeoJsonMultiLineString,
    GeoJsonPolygon,
    AllocatedStation,
    AllocationRoute,
    AllocationSettlement,
    FloodAdvisory,
    FloodDetails,
    FloodHydrometricStation,
    FloodResponseSite,
    FloodRoad,
    FloodRoadVerification,
    FloodSharedEvent,
    FireDetails,
    FireSharedEvent,
    FloodSourceContext,
    FloodStream,
    FireResponseAction,
    GenericSharedEvent,
    GeographicPoint,
    MinistryAirQualityIndex,
    OfficialPollutantClassification,
    ProtocolCitation,
    TransportTimeEvidence,
    ResourceAllocationSummary,
    VerifiedReference,
)

logger = logging.getLogger(__name__)

IncidentReader = Callable[[str], dict[str, Any] | None]
ProjectionWriter = Callable[[EventProjectionWrite], dict[str, Any] | None]
ProjectionReader = Callable[[str], dict[str, Any] | None]
EventMapper = Callable[
    [IncidentProcessingResult, Mapping[str, Any]],
    AirPollutionSharedEvent
    | EarthquakeSharedEvent
    | FireSharedEvent
    | FloodSharedEvent
    | GenericSharedEvent,
]


@dataclass(frozen=True)
class ProjectionOutcome:
    incident_id: str
    status: str
    persisted: bool
    reason: str | None = None


def _analysis_candidate(result, incident):
    """The pollution reading this event should be shown as.

    Prefers a detection the analysis actually cited, falls back to the newest
    one it looked at, and finally to the newest on the incident itself.
    """
    analysis = result.analysis_result
    if analysis is not None:
        state = analysis.current_state.result
        if state is not None and state.detections:
            referenced_ids = set(analysis.analysis_origin.evidence_reference_ids)
            referenced = [
                item
                for item in state.detections
                if item.anomaly.detection_id in referenced_ids
            ]
            if referenced:
                return max(
                    referenced,
                    key=lambda item: item.anomaly.observed_at,
                )
            return max(state.detections, key=lambda item: item.anomaly.observed_at)
    return max(
        pollution_candidates_from_incident(incident),
        key=lambda item: item.anomaly.observed_at,
    )


def _component_gaps(result) -> list[ComponentUnavailableReason]:
    """Everything the analysis could not determine, with its reason.

    Collected so the card can say what is missing instead of leaving a blank
    that reads like a zero.
    """
    gaps = []
    analysis = result.analysis_result
    if analysis is not None:
        for name, component in (
            ("ministry_aqi", analysis.severity_assessment),
            ("trend", analysis.future_prediction),
            ("transport", analysis.transport_analysis),
            ("population", analysis.population_impact),
        ):
            if component.status == "unavailable":
                gaps.append(ComponentUnavailableReason(
                    component=name,
                    reason=component.unavailable_reason or "unavailable",
                ))
    if result.failure_stage:
        gaps.append(ComponentUnavailableReason(
            component=result.failure_stage,
            reason=result.failure_reason or "processing_failed",
        ))
    planning = result.planner_result
    if planning is not None and planning.plan.status != "success":
        gaps.append(ComponentUnavailableReason(
            component="planner",
            reason=planning.plan.reason or planning.plan.status,
        ))
    return gaps


def air_pollution_shared_event(
    result: IncidentProcessingResult,
    incident: Mapping[str, Any],
) -> AirPollutionSharedEvent:
    """Project only preserved/analyzed facts; never infer scientific values."""

    if result.hazard != "air_pollution" or result.route != "non_emergency":
        raise ValueError("not_an_air_pollution_advisory_result")
    candidate = _analysis_candidate(result, incident)
    anomaly = candidate.anomaly
    baseline = anomaly.baseline_evidence
    analysis = result.analysis_result
    planning = result.planner_result

    ministry = None
    wind = None
    transport = None
    settlements = []
    settlement_context = (
        AirPollutionSettlementContext.model_validate(
            candidate.spatial_context.settlement_context.model_dump(mode="json")
        )
        if candidate.spatial_context is not None
        and candidate.spatial_context.settlement_context is not None
        else None
    )
    population = None
    trend = None
    official_classification = None
    publication = None
    verification = None
    limitations = []
    if analysis is not None:
        limitations.extend(analysis.limitations)
        if analysis.official_pollutant_classification is not None:
            official_classification = OfficialPollutantClassification.model_validate(
                analysis.official_pollutant_classification.model_dump(mode="json")
            )
        if analysis.publication_policy is not None:
            publication = AirPollutionPublicationPolicy.model_validate(
                analysis.publication_policy.model_dump(mode="json")
            )
        if analysis.additional_verification is not None:
            verification = AirPollutionAdditionalVerification.model_validate(
                analysis.additional_verification.model_dump(mode="json")
            )
        severity = analysis.severity_assessment.result
        if severity is not None:
            index = severity.ministry_index
            ministry = MinistryAirQualityIndex(
                station_id=index.station_id,
                pollutant=index.pollutant,
                resolved_channel_id=index.resolved_channel_id,
                station_index=index.station_index,
                station_category=index.station_category,
                category_color=index.category_color,
                pollutant_sub_index=index.pollutant_sub_index,
                driving_pollutant=index.driving_pollutant,
                averaged_concentration=index.averaged_concentration,
                averaging_period_minutes=index.averaging_period_minutes,
                provider_timestamp=index.provider_timestamp,
                preliminary=index.preliminary,
                source=index.source,
            )
        prediction = analysis.future_prediction.result
        if prediction is not None:
            trend = prediction.trend
        execution = analysis.transport_analysis.result
        if execution is not None:
            wind_evidence = execution.wind_evidence
            wind = AirPollutionWindEvidence(
                provider=wind_evidence.provider,
                source_type=wind_evidence.source_type,
                provider_location_name=wind_evidence.provider_location_name,
                observed_or_valid_at=wind_evidence.effective_at,
                wind_from_direction_deg=wind_evidence.wind_from_direction_deg,
                wind_speed_mps=wind_evidence.wind_speed_mps,
                gust_from_direction_deg=wind_evidence.gust_from_direction_deg,
                gust_speed_mps=wind_evidence.gust_speed_mps,
                direction_stddev_deg=wind_evidence.direction_stddev_deg,
                reference=wind_evidence.reference,
                evidence_id=wind_evidence.evidence_id,
            )
            spatial = execution.spatial_output
            if spatial.settlement_context is not None:
                settlement_context = AirPollutionSettlementContext.model_validate(
                    spatial.settlement_context.model_dump(mode="json")
                )
            population_result = analysis.population_impact.result
            geometry_reference = (
                population_result.geometry_reference
                if population_result is not None
                else None
            )
            transport = AirPollutionTransportScreening(
                corridor=(
                    GeoJsonPolygon.model_validate(
                        spatial.corridor_polygon.model_dump(mode="json")
                    )
                    if spatial.corridor_polygon is not None else None
                ),
                centerline=(
                    GeoJsonLineString.model_validate(
                        spatial.centerline.model_dump(mode="json")
                    )
                    if spatial.centerline is not None else None
                ),
                downwind_to_direction_deg=spatial.downwind_to_direction_deg,
                corridor_method=spatial.corridor_method,
                corridor_half_angle_deg=spatial.corridor_half_angle_deg,
                max_screening_distance_m=spatial.max_screening_distance_m,
                direction_stddev_deg=spatial.direction_stddev_deg,
                geometry_reference=geometry_reference,
            )
            settlements = [
                AirPollutionSettlement(
                    id=item.settlement_id,
                    name=item.name,
                    longitude=item.point.coordinates[0],
                    latitude=item.point.coordinates[1],
                    inside_transport_corridor=item.inside_transport_corridor,
                    rank=item.rank,
                    potential_downwind_relevance=item.potential_downwind_relevance,
                    distance_m=item.geodesic_distance_m,
                    transport_time=TransportTimeEvidence(
                        status=(
                            "estimated"
                            if item.kinematic_advection_time_seconds is not None
                            else "unavailable"
                        ),
                        seconds=item.kinematic_advection_time_seconds,
                        method=item.transport_time_method,
                        assumptions=item.transport_time_assumptions,
                        unavailable_reason=(
                            None
                            if item.kinematic_advection_time_seconds is not None
                            else "transport_time_not_estimated"
                        ),
                    ),
                )
                for item in spatial.settlements
            ]
        population_result = analysis.population_impact.result
        if population_result is not None:
            population = CorridorPopulationContext(
                total_relevant_population=population_result.total_relevant_population,
                intersected_cell_count=population_result.intersected_cell_count,
                queried_at=population_result.queried_at,
                geometry_reference=population_result.geometry_reference,
                dataset_reference_year=population_result.dataset_reference_year,
            )

    recommendations = []
    references = []
    description = (
        f"Historically unusual {anomaly.pollutant} measurement at "
        f"{anomaly.station_name or anomaly.station_id}."
    )
    if planning is not None:
        plan = planning.plan
        limitations.extend(plan.limitations)
        if plan.status == "success":
            description = plan.summary or description
            recommendations = [
                AirPollutionRecommendation(
                    recommendation=item.recommendation,
                    rationale=item.rationale,
                    responsible_authority_type=item.responsible_authority_type,
                    resource_type=item.resource_type,
                    timeframe=item.timeframe,
                    priority=item.priority,
                    spatial_relevance=item.spatial_relevance,
                )
                for item in plan.actions
            ]
            references = [
                VerifiedReference(
                    id=item.chunk_id,
                    document_title=item.document_title,
                    source_url=item.source_url,
                    quoted_text=item.quoted_text,
                    supports=item.supports,
                    verified=True,
                )
                for item in plan.protocol_references
            ]

    limitations.extend([
        "p95 represents historical unusualness, not health severity.",
        "The monitoring location is not a confirmed emission source.",
        "Transport geometry is possible screening, not a confirmed plume or exposure area.",
        "Population is geographically intersecting the screening corridor, not confirmed affected or exposed population.",
    ])
    analysis_status = result.analysis_status or (
        "failed" if result.failure_stage in {"adaptation", "analysis", "handler"}
        else "skipped"
    )
    planning_status = result.planner_status or (
        "failed" if result.failure_stage == "planning" else "skipped"
    )
    return AirPollutionSharedEvent(
        id=result.incident_id,
        type="air_pollution",
        title=(
            f"Air pollution advisory: {anomaly.pollutant} at "
            f"{anomaly.station_name or anomaly.station_id}"
        ),
        description=description,
        latitude=anomaly.location.latitude,
        longitude=anomaly.location.longitude,
        observed_at=anomaly.observed_at,
        classification="advisory",
        analysis_status=analysis_status,
        planning_status=planning_status,
        details=AirPollutionDetails(
            pollutant=anomaly.pollutant,
            station=AirPollutionStation(
                id=anomaly.station_id,
                name=anomaly.station_name,
                provider=anomaly.provider,
                channel_id=anomaly.channel_id,
            ),
            measured_value=anomaly.value,
            unit=anomaly.unit,
            observation_timestamp=anomaly.observed_at,
            historical_baseline=AirPollutionBaselineContext(
                p95=baseline.statistics.p95,
                month=baseline.month,
                hour=baseline.hour,
                sample_count=baseline.statistics.sample_count,
                distinct_days=baseline.statistics.distinct_days,
                distinct_years=baseline.statistics.distinct_years,
                baseline_family=baseline.identity.baseline_family,
                baseline_version_id=baseline.version.baseline_version_id,
                baseline_content_sha256=baseline.version.content_sha256,
            ),
            ministry_aqi=ministry,
            official_pollutant_classification=official_classification,
            publication_policy=publication,
            additional_verification=verification,
            wind=wind,
            transport=transport,
            relevant_settlements=settlements,
            settlement_context=settlement_context,
            population_within_screening_corridor=population,
            recommendations=recommendations,
            verified_references=references,
            unavailable_components=_component_gaps(result),
            limitations=list(dict.fromkeys(limitations)),
            trend=trend,
        ),
    )


def _flood_station_sources(
    targeting: Mapping[str, Any],
    incident: Mapping[str, Any],
    analysis: FloodEventAnalysis | None = None,
) -> list[dict[str, Any]]:
    """The gauges behind a flood event, with their readings and thresholds.

    Reads the targeting result first and falls back to the incident's own
    signals, so a card still names its source when targeting was unavailable.
    """
    sources = targeting.get("hydrometric_sources")
    if isinstance(sources, list) and sources:
        return [dict(item) for item in sources if isinstance(item, Mapping)]

    # When a de-escalation intentionally skips road targeting, project the
    # analyzer's latest per-station state. Reconstructing every historical
    # signal here would incorrectly keep showing the incident's peak band.
    if analysis is not None and analysis.current_state is not None:
        current_sources = []
        for state in analysis.current_state.stations:
            if (
                state.latitude is None
                or state.longitude is None
                or not 3 <= state.severity_level <= 6
            ):
                continue
            current_sources.append({
                "station": {
                    "id": state.station_id,
                    "latitude": state.latitude,
                    "longitude": state.longitude,
                    "precision_m": state.precision_m,
                    "severity_level": state.severity_level,
                    "observed_at": state.observed_at,
                    "stream_match": "unmatched",
                },
                "strategy": "analyzer_current_state",
                "stream": None,
            })
        if current_sources:
            return current_sources

    reconstructed = []
    for signal in incident.get("signals") or []:
        if not isinstance(signal, Mapping) or signal.get("hazard") != "flood":
            continue
        evidence = signal.get("evidence") or {}
        location = signal.get("location") or {}
        if not isinstance(evidence, Mapping) or not isinstance(location, Mapping):
            continue
        try:
            station_id = int(evidence.get("source_station_id", evidence.get("station_id")))
            severity = int(evidence["severity_level"])
            latitude = float(location["latitude"])
            longitude = float(location["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        reconstructed.append({
            "station": {
                "id": station_id,
                "latitude": latitude,
                "longitude": longitude,
                "precision_m": max(0.0, float(location.get("precision_m") or 0.0)),
                "severity_level": severity,
                "observed_at": signal.get("observed_at"),
                "stream_match": "unmatched",
            },
            "strategy": "spatial_lookup_unavailable",
            "stream": None,
        })
    return reconstructed


def _flood_stream(value: Any) -> FloodStream | None:
    """One stream's drawable geometry, or None if it is not usable.

    Accepts a single line or a set of lines and rejects anything else, so a
    malformed shape is dropped rather than breaking the whole map layer.
    """
    if not isinstance(value, Mapping) or not isinstance(value.get("geometry"), Mapping):
        return None
    geometry = value["geometry"]
    if geometry.get("type") == "LineString":
        parsed_geometry = GeoJsonLineString.model_validate(geometry)
    elif geometry.get("type") == "MultiLineString":
        parsed_geometry = GeoJsonMultiLineString.model_validate(geometry)
    else:
        return None
    return FloodStream(
        stream_id=value.get("stream_id"),
        water_source_id=int(value["water_source_id"]),
        name=value.get("stream_name") or value.get("name"),
        match_confidence=value.get("match_confidence"),
        geometry=parsed_geometry,
    )


def _allocation_summary(value: Any) -> ResourceAllocationSummary | None:
    """What the allocator reserved, flattened for the event card.

    Turns the per-unit-type groups into one station list and keeps the
    shortages, so the card can show what was asked for and what was missing.
    """
    if not isinstance(value, Mapping):
        return None
    stations = []
    allocated = value.get("allocated_units") or {}
    if isinstance(allocated, Mapping):
        for assigned in allocated.values():
            for station in assigned if isinstance(assigned, list) else []:
                if not isinstance(station, Mapping):
                    continue
                route_value = station.get("route")
                route = None
                if isinstance(route_value, Mapping):
                    route = AllocationRoute.model_validate({
                        key: route_value.get(key)
                        for key in (
                            "status", "provider", "profile", "distance_m",
                            "duration_s", "geometry", "origin", "destination",
                            "estimated_arrival_at", "road_access_verified",
                            "requires_field_access_confirmation", "offroad_segment",
                            "steps_he", "error",
                        )
                        if key in route_value
                    })
                stations.append(AllocatedStation(
                    database_id=int(station["database_id"]),
                    name=str(station["name"]),
                    address=station.get("address"),
                    unit_type=str(station["unit_type"]),
                    recommended_unit=str(station["recommended_unit"]),
                    latitude=float(station["latitude"]),
                    longitude=float(station["longitude"]),
                    distance_km=station.get("distance_km"),
                    allocation_status=str(station["allocation_status"]),
                    selection_reason=str(station["selection_reason"]),
                    response_actions=[
                        FireResponseAction.model_validate(action)
                        for action in station.get("response_actions") or []
                        if isinstance(action, Mapping)
                    ],
                    route=route,
                ))
    settlement_value = value.get("settlement")
    return ResourceAllocationSummary(
        status=str(value.get("status") or "unavailable"),
        routing_status=str(value.get("routing_status") or "not_available"),
        requirements=dict(value.get("requirements") or {}),
        shortages=dict(value.get("shortages") or {}),
        stations=stations,
        errors=[dict(item) for item in value.get("errors") or [] if isinstance(item, Mapping)],
        settlement=(
            AllocationSettlement.model_validate(settlement_value)
            if isinstance(settlement_value, Mapping) else None
        ),
    )


def flood_shared_event(
    result: IncidentProcessingResult,
    incident: Mapping[str, Any],
) -> FloodSharedEvent:
    """Project observed gauges, exact matched streams and operational sites."""

    if result.hazard != "flood" or result.route != "emergency":
        raise ValueError("not_a_flood_emergency_result")
    analysis = (
        result.analysis_result
        if isinstance(result.analysis_result, FloodEventAnalysis)
        else None
    )
    risk = (
        result.risk_assessment
        if isinstance(result.risk_assessment, FloodRiskAssessment)
        else None
    )
    targeting = result.resource_allocation_result or {}
    sources = _flood_station_sources(targeting, incident, analysis)
    if not sources:
        raise ValueError("hydrometric_station_evidence_unavailable")

    projected_sources = []
    for source in sources:
        station_value = source.get("station") or {}
        station = FloodHydrometricStation.model_validate({
            **station_value,
            "stream_match": "matched" if source.get("stream") is not None else "unmatched",
        })
        projected_sources.append(FloodSourceContext(
            station=station,
            strategy=str(source.get("strategy") or "unknown"),
            stream=_flood_stream(source.get("stream")),
        ))

    sites = []
    for site in targeting.get("response_sites") or []:
        if not isinstance(site, Mapping):
            continue
        verification = site.get("mapbox_verification") or {}
        sites.append(FloodResponseSite(
            target_id=str(site["target_id"]),
            source_station_id=int(site["source_station_id"]),
            severity_level=int(site["severity_level"]),
            strategy=str(site["strategy"]),
            road=FloodRoad(
                **{
                    key: value
                    for key, value in dict(site.get("road") or {}).items()
                    if key not in {"class", "road_class"}
                },
                road_class=(site.get("road") or {}).get("class")
                or (site.get("road") or {}).get("road_class"),
            ),
            crossing_type=site.get("crossing_type"),
            urban=site.get("urban") is True,
            crossing_location=GeographicPoint.model_validate(site["crossing_location"]),
            allocation_location=(
                GeographicPoint.model_validate(site["allocation_location"])
                if isinstance(site.get("allocation_location"), Mapping) else None
            ),
            allocation_eligible=site.get("allocation_eligible") is True,
            local_match_confidence=str(site.get("local_match_confidence") or "unknown"),
            mapbox_verification=FloodRoadVerification(
                status=str(verification.get("status") or "unavailable"),
                verified=verification.get("verified") is True,
                reason=verification.get("reason"),
                mapbox_snap_distance_m=verification.get("mapbox_snap_distance_m"),
            ),
        ))

    primary_station_id = (
        analysis.current_state.primary_station_id
        if analysis is not None and analysis.current_state is not None
        else None
    )
    primary = next(
        (
            source
            for source in projected_sources
            if source.station.id == primary_station_id
        ),
        max(projected_sources, key=lambda item: item.station.severity_level),
    )
    severity = (
        analysis.current_state.severity_level
        if analysis is not None and analysis.current_state is not None
        else primary.station.severity_level
    )
    return_period = {3: "10-year", 4: "20-year", 5: "50-year", 6: "100-year"}[severity]
    drawable_streams = sum(source.stream is not None for source in projected_sources)
    targeting_status = targeting.get("status")
    change = analysis.change_assessment if analysis is not None else None
    preserving = result.preserve_existing_response
    plan = (
        result.planner_result
        if isinstance(result.planner_result, Mapping)
        else {}
    )
    plan_actions = [
        FireResponseAction.model_validate({
            "action": action.get("action"),
            "responsible_unit": action.get("responsible_unit"),
            "timeframe": action.get("timeframe"),
            "supporting_protocol_chunk_ids": (
                action.get("supporting_protocol_chunk_ids") or []
            ),
        })
        for action in plan.get("response_actions") or []
        if isinstance(action, Mapping)
    ]
    return FloodSharedEvent(
        id=result.incident_id,
        title=f"Flood warning: hydrometric station {primary.station.id}",
        description=(
            f"Hydrometric Flood warning at station {primary.station.id}; "
            f"{len(sites)} relevant road site(s) identified."
        ),
        latitude=primary.station.latitude,
        longitude=primary.station.longitude,
        observed_at=primary.station.observed_at,
        classification="emergency",
        analysis_status=(
            analysis.status
            if analysis is not None
            else "success"
            if targeting_status not in {None, "failed", "not_evaluated"}
            else "partial"
        ),
        planning_status=(
            result.planner_status
            or (
                "success"
                if targeting_status not in {None, "failed", "not_evaluated"}
                else "unavailable"
            )
        ),
        details=FloodDetails(
            severity_level=severity,
            return_period_label=return_period,
            risk_status=(risk.metadata.analysis_status if risk is not None else None),
            risk_score=(risk.risk_score if risk is not None else None),
            risk_level=(risk.risk_level if risk is not None else None),
            risk_confidence=(risk.confidence if risk is not None else None),
            risk_primary_drivers=(
                list(risk.primary_drivers) if risk is not None else []
            ),
            risk_explanation=(risk.explanation if risk is not None else None),
            sources=projected_sources,
            response_sites=sites,
            allocation_ready_site_ids=[site.target_id for site in sites if site.allocation_eligible],
            targeting_status=(
                "preserved_existing_response"
                if preserving and not targeting
                else str(targeting_status or "unavailable")
            ),
            targeting_reason=targeting.get("reason"),
            allocation_target=targeting.get("allocation_target"),
            advisories=[
                FloodAdvisory.model_validate(advisory)
                for advisory in targeting.get("advisories") or []
                if isinstance(advisory, Mapping)
            ],
            response_actions=plan_actions,
            assumptions=[str(item) for item in plan.get("assumptions") or []],
            evidence_gaps=list(dict.fromkeys([
                *(analysis.evidence_gaps if analysis is not None else []),
                *(risk.evidence_gaps if risk is not None else []),
                *[str(item) for item in plan.get("evidence_gaps") or []],
            ])),
            resource_allocation=_allocation_summary(targeting.get("station_allocation")),
            response_plan=(
                dict(result.planner_result)
                if isinstance(result.planner_result, Mapping)
                else None
            ),
            change_type=change.change_type if change is not None else None,
            threshold_transition=(
                change.threshold_transition if change is not None else None
            ),
            response_refresh_required=result.response_refresh_required,
            existing_response_preserved=preserving,
            limitations=[
                "The stream line marks the stream under warning, not confirmed inundation extent.",
                "A ring around an unmatched station represents location precision, not flood extent.",
                f"Drawable matched stream geometries: {drawable_streams} of {len(projected_sources)}.",
                *(analysis.limitations if analysis is not None else []),
                *(risk.limitations if risk is not None else []),
                *[str(item) for item in plan.get("limitations") or []],
            ],
        ),
    )


def _preserve_flood_operational_response(
    event: FloodSharedEvent,
    previous_projection: Mapping[str, Any] | None,
) -> FloodSharedEvent:
    """Carry forward the last plan/targets while keeping new hydrology."""

    if not previous_projection:
        return event
    payload = (
        previous_projection.get("last_successful_event_payload")
        or previous_projection.get("event_payload")
    )
    if not isinstance(payload, Mapping):
        return event
    previous_details = payload.get("details")
    if not isinstance(previous_details, Mapping):
        return event

    details = event.details.model_dump(mode="json")
    for key in (
        "response_sites",
        "allocation_ready_site_ids",
        "targeting_reason",
        "allocation_target",
        "advisories",
        "resource_allocation",
        "response_plan",
        "response_actions",
        "assumptions",
    ):
        if key in previous_details:
            details[key] = previous_details[key]

    for key in ("evidence_gaps", "limitations"):
        details[key] = list(dict.fromkeys([
            *(details.get(key) or []),
            *(previous_details.get(key) or []),
        ]))

    # Retain a previously verified stream geometry for a station, but never
    # copy its old severity or timestamp over the current analyzer state.
    previous_sources = {
        item.get("station", {}).get("id"): item
        for item in previous_details.get("sources") or []
        if isinstance(item, Mapping) and isinstance(item.get("station"), Mapping)
    }
    for source in details.get("sources") or []:
        if not isinstance(source, dict) or source.get("stream") is not None:
            continue
        station = source.get("station") or {}
        previous = previous_sources.get(station.get("id"))
        if isinstance(previous, Mapping) and previous.get("stream") is not None:
            source["stream"] = previous["stream"]
            source["strategy"] = previous.get("strategy") or source.get("strategy")
            station["stream_match"] = "matched"

    preserved_details = FloodDetails.model_validate(details)
    return event.model_copy(update={
        "details": preserved_details,
        "description": (
            f"Hydrometric Flood warning at station "
            f"{preserved_details.sources[0].station.id}; "
            f"{len(preserved_details.response_sites)} relevant road site(s) identified."
        ),
    })


def default_mapper_registry() -> dict[tuple[str, str], EventMapper]:
    """Which function turns each hazard and route into a dashboard event."""
    return {
        ("air_pollution", "non_emergency"): air_pollution_shared_event,
        ("earthquake", "emergency"): earthquake_shared_event,
        ("fire", "emergency"): fire_processing_shared_event,
        ("flood", "emergency"): flood_shared_event,
        # One mapper, every hazard. An unconfirmed report is projected the same
        # way whatever it claims to be, because none of the hazard-specific
        # detail exists for it — there is no analysis to project.
        **{
            (hazard, "uncorroborated"): uncorroborated_shared_event
            for hazard in ("fire", "flood", "earthquake", "air_quality", "air_pollution")
        },
    }


def uncorroborated_shared_event(
    result: IncidentProcessingResult,
    incident: Mapping[str, Any],
) -> GenericSharedEvent:
    """Project an unverified report as its own event type.

    Deliberately `type="other"` and `classification="advisory"` rather than a
    fire or a flood. The map, the incident list and anything else reading this
    feed keys off `type`, and a rumour rendered with the same marker as a
    satellite-confirmed fire is the one presentation error in this system that
    could send someone to the wrong place. The claimed hazard is carried inside
    `details` where it cannot be mistaken for a confirmed one.
    """
    if result.route != "uncorroborated":
        raise ValueError("not_an_uncorroborated_result")

    plan = result.planner_result if isinstance(result.planner_result, Mapping) else {}
    hazard = str(plan.get("hazard") or result.hazard)
    place = plan.get("location_text") or "an unnamed location"

    return GenericSharedEvent(
        id=str(incident["id"]),
        type="other",
        title=f"Unverified {hazard.replace('_', ' ')} report — {place}",
        description=str(
            plan.get("summary")
            or "An unverified public report. Nothing corroborates it yet."
        ),
        latitude=float(incident["latitude"]),
        longitude=float(incident["longitude"]),
        observed_at=incident.get("last_signal_at"),
        classification="advisory",
        # There was no analysis, and saying "success" here would claim one
        # happened. `skipped` is the honest word and the handler sets it.
        analysis_status=result.analysis_status or "skipped",
        planning_status=result.planner_status or "skipped",
        details={
            "kind": "uncorroborated_report",
            "claimed_hazard": hazard,
            "corroborated": False,
            "claim": plan.get("claim"),
            "location_text": plan.get("location_text"),
            "advisory": plan.get("actions") or [],
            "contacts": plan.get("contacts") or {},
            "limitations": plan.get("limitations") or [],
        },
    )


def fire_shared_event(
    detected_event: Mapping[str, Any],
    risk_assessment: Mapping[str, Any] | None = None,
    planner: Mapping[str, Any] | None = None,
    *,
    incident_id: str,
) -> FireSharedEvent:
    """Project DetectedFireEvent, RiskAnalysisAgent and emergency-plan output."""

    risk = risk_assessment or {}
    plan = planner or {}
    location = detected_event.get("location") or {}
    latitude = float(location["latitude"])
    longitude = float(location["longitude"])
    geospatial = detected_event.get("geospatial_context") or {}
    settlements = geospatial.get("nearby_settlements") or ()
    named_settlement = next(
        (
            str(item["name"])
            for item in settlements
            if isinstance(item, Mapping) and item.get("name")
        ),
        None,
    )
    title = (
        f"Fire detected near {named_settlement}"
        if named_settlement
        else f"Fire at {latitude:.3f}, {longitude:.3f}"
    )

    response_actions = [
        FireResponseAction.model_validate(item)
        for item in plan.get("response_actions") or ()
    ]
    citations = [
        ProtocolCitation.model_validate(item)
        for item in [
            *((risk.get("grounding") or {}).get("citations") or ()),
            *((plan.get("grounding") or {}).get("citations") or ()),
        ]
    ]
    risk_status = str(
        (risk.get("metadata") or {}).get("analysis_status") or "failed"
    )
    planning_status = str(
        (plan.get("metadata") or {}).get("planning_status") or "skipped"
    )
    valid_statuses = {"success", "partial", "unavailable", "failed", "skipped"}
    if risk_status not in valid_statuses:
        risk_status = "failed"
    if planning_status not in valid_statuses:
        planning_status = "failed"

    details = FireDetails(
        detection_confidence=detected_event.get("detection_confidence"),
        fire_weather_severity=detected_event.get("fire_weather_severity"),
        risk_score=risk.get("risk_score"),
        risk_level=risk.get("risk_level"),
        confidence=risk.get("confidence"),
        primary_drivers=list(risk.get("primary_drivers") or ()),
        explanation=risk.get("explanation"),
        assumptions=list(plan.get("assumptions") or ()),
        evidence_gaps=list(dict.fromkeys([
            *[str(item) for item in risk.get("evidence_gaps") or ()],
            *[str(item) for item in plan.get("evidence_gaps") or ()],
        ])),
        limitations=list(dict.fromkeys([
            *[str(item) for item in risk.get("limitations") or ()],
            *[str(item) for item in plan.get("limitations") or ()],
        ])),
        recommended_units=list(plan.get("recommended_units") or ()),
        response_plan=[item.action for item in response_actions],
        response_actions=response_actions,
        protocol_citations=citations,
        incident_report=risk.get("explanation"),
    )
    return FireSharedEvent(
        id=incident_id,
        title=title,
        description=(
            plan.get("plan_summary")
            or risk.get("explanation")
            or "A fire incident was detected; operational analysis is unavailable."
        ),
        latitude=latitude,
        longitude=longitude,
        observed_at=None,
        classification="emergency",
        analysis_status=risk_status,
        planning_status=planning_status,
        details=details,
    )


def fire_processing_shared_event(
    result: IncidentProcessingResult,
    incident: Mapping[str, Any],
) -> FireSharedEvent:
    """Project the shared Fire handler result, allocation and observation time."""

    if result.hazard != "fire" or result.route != "emergency":
        raise ValueError("not_a_fire_emergency_result")
    if not isinstance(result.analysis_result, Mapping):
        raise ValueError("fire_analysis_missing")
    risk = (
        result.risk_assessment
        if isinstance(result.risk_assessment, Mapping)
        else None
    )
    planner = (
        result.planner_result
        if isinstance(result.planner_result, Mapping)
        else None
    )
    event = fire_shared_event(
        result.analysis_result,
        risk,
        planner,
        incident_id=result.incident_id,
    )
    details = event.details.model_copy(update={
        "resource_allocation": _allocation_summary(
            result.resource_allocation_result
        ),
    })
    return event.model_copy(update={
        "latitude": event.latitude,
        "longitude": event.longitude,
        "observed_at": incident.get("last_signal_at") or incident.get("first_seen_at"),
        "analysis_status": result.risk_status or event.analysis_status,
        "planning_status": result.planner_status or event.planning_status,
        "details": details,
    })


def earthquake_shared_event(
    result: IncidentProcessingResult,
    incident: Mapping[str, Any],
) -> EarthquakeSharedEvent:
    """Project deterministic screening facts without invoking a planner."""

    if result.hazard != "earthquake" or result.route != "emergency":
        raise ValueError("not_an_earthquake_emergency_result")
    impact = result.analysis_result
    if impact is None:
        raise ValueError("earthquake_impact_missing")
    towns_available = impact.towns.status.value.startswith("SUCCESS")
    plan = result.planner_result if isinstance(result.planner_result, dict) else {}
    allocation = (
        result.resource_allocation_result
        if isinstance(result.resource_allocation_result, dict)
        else None
    )
    allocation_summary = None
    if allocation is not None:
        stations = [
            station
            for group in (allocation.get("allocated_units") or {}).values()
            for station in group
        ]
        allocation_summary = {
            "status": allocation.get("status", "failed"),
            "routing_status": allocation.get("routing_status", "not_available"),
            "requirements": allocation.get("requirements") or {},
            "shortages": allocation.get("shortages") or {},
            "stations": [
                {
                    "database_id": station["database_id"],
                    "name": station.get("name") or f"Station {station['database_id']}",
                    "address": station.get("address"),
                    "unit_type": station["unit_type"],
                    "recommended_unit": station["recommended_unit"],
                    "latitude": station["latitude"],
                    "longitude": station["longitude"],
                    "distance_km": station.get("distance_km"),
                    "allocation_status": station.get("allocation_status", "assigned"),
                    "selection_reason": station.get("selection_reason", "unknown"),
                    "route": station.get("route"),
                }
                for station in stations
            ],
            "errors": [
                error for error in allocation.get("errors") or []
                if isinstance(error, dict)
            ],
            "unsupported_units": allocation.get("unsupported_units") or [],
            "allocation_policy": allocation.get("allocation_policy"),
            "allocation_basis": allocation.get("allocation_basis"),
            "quantity_source": allocation.get("quantity_source"),
        }
    actions = [
        {
            "action": action["action"],
            "responsible_unit": action["responsible_unit"],
            "timeframe": action["timeframe"],
        }
        for action in plan.get("response_actions") or []
    ]
    return EarthquakeSharedEvent(
        id=str(incident["id"]),
        title=f"Earthquake M{impact.magnitude:.1f}",
        description="GSI earthquake with a deterministic Estimated Impact Area.",
        latitude=impact.latitude,
        longitude=impact.longitude,
        observed_at=impact.observed_at,
        classification="emergency",
        analysis_status="success",
        planning_status=result.planner_status or "skipped",
        details=EarthquakeDetails(
            provider_event_id=impact.provider_event_id,
            magnitude=impact.magnitude,
            depth_km=impact.depth_km,
            estimated_impact_radius_km=impact.radius_km,
            estimated_impact_area=GeoJsonPolygon.model_validate(impact.area),
            towns=[
                EarthquakeTown(
                    town_id=town.town_id,
                    name_he=town.name_he,
                    name_en=town.name_en,
                    cbs_code=town.cbs_code,
                )
                for town in impact.towns.towns
            ],
            towns_status="available" if towns_available else "unavailable",
            population_summary=EarthquakePopulationSummary(
                **impact.population_summary
            ),
            provider=impact.provider,
            source=impact.source,
            plan_summary=plan.get("plan_summary"),
            recommended_units=plan.get("recommended_units") or [],
            response_actions=actions,
            protocol_citations=(plan.get("grounding") or {}).get("citations") or [],
            evidence_gaps=plan.get("evidence_gaps") or [],
            limitations=list(dict.fromkeys([
                "Estimated Impact Area is a screening radius only; it does not "
                "model soil conditions, shaking intensity, building vulnerability, "
                "or actual damage.",
                *(plan.get("limitations") or []),
            ])),
            resource_allocation=allocation_summary,
        ),
    )


def _retryable(result: IncidentProcessingResult) -> bool:
    """Whether this failure is worth attempting again later.

    True for anything that failed in analysis or planning, since those can
    succeed on a later pass. The dispatcher decides when, and gives up after a
    few tries.
    """
    return bool(
        result.status == "failed"
        or result.failure_stage
        in {"adaptation", "analysis", "risk_analysis", "planning", "handler"}
        or result.analysis_status == "failed"
        or result.planner_status == "failed"
    )


def project_processing_results(
    results: Sequence[IncidentProcessingResult],
    *,
    mapper_registry: Mapping[tuple[str, str], EventMapper] | None = None,
    incident_reader: IncidentReader = incident_store.incident_by_id,
    projection_reader: ProjectionReader = event_projection_by_incident,
    writer: ProjectionWriter = upsert_event_projection,
) -> list[ProjectionOutcome]:
    """Project and persist each result independently; unsupported skips vanish."""

    mappers = mapper_registry or default_mapper_registry()
    outcomes = []
    for result in results:
        mapper = mappers.get((result.hazard, result.route))
        if mapper is None or result.status == "skipped":
            outcomes.append(ProjectionOutcome(
                result.incident_id, "skipped", False, "unsupported_or_skipped"
            ))
            continue
        incident = incident_reader(result.incident_id)
        if incident is None:
            outcomes.append(ProjectionOutcome(
                result.incident_id, "failed", False, "incident_not_found"
            ))
            continue

        event = None
        mapping_failure = None
        try:
            event = mapper(result, incident)
            if (
                isinstance(event, FloodSharedEvent)
                and result.preserve_existing_response
            ):
                event = _preserve_flood_operational_response(
                    event,
                    projection_reader(result.incident_id),
                )
        except Exception as error:
            mapping_failure = type(error).__name__
            logger.exception("event mapping failed for %s", result.incident_id)

        analysis_status = event.analysis_status if event else result.analysis_status
        planning_status = event.planning_status if event else result.planner_status
        retryable = _retryable(result) or mapping_failure is not None
        successful = bool(
            event is not None
            and analysis_status in {"success", "partial"}
            and (
                planning_status == "success"
            )
        )
        record = EventProjectionWrite(
            incident_id=result.incident_id,
            hazard=result.hazard,
            route=result.route,
            processing_status=result.status,
            analysis_status=analysis_status,
            planner_status=planning_status,
            analysis_id=result.analysis_id,
            coordinator_routing_id=result.coordinator_routing_id,
            handler=result.handler,
            event_payload=(event.model_dump(mode="json") if event else None),
            failure_stage=("projection" if mapping_failure else result.failure_stage),
            failure_reason=mapping_failure or result.failure_reason,
            retryable=retryable,
            successful=successful,
            attempted_at=result.requested_at,
            processed_at=result.completed_at,
        )
        try:
            writer(record)
        except Exception:
            logger.exception("event projection persistence failed for %s", result.incident_id)
            outcomes.append(ProjectionOutcome(
                result.incident_id, "failed", False, "projection_persistence_failed"
            ))
            continue
        outcomes.append(ProjectionOutcome(
            result.incident_id,
            "success" if successful else "partial" if event else "failed",
            True,
            mapping_failure,
        ))
    return outcomes
