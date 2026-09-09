"""Translate stored pollution domain state into the existing frontend event contract."""

from services.air_pollution_event_store import (
    AirPollutionRuntimeSnapshot,
    StoredAirPollutionEvent,
)


def build_air_pollution_event(result: StoredAirPollutionEvent) -> dict:
    candidate = result.event
    anomaly = candidate.anomaly
    pollutants = candidate.pollutants
    pollutant_label = " / ".join(pollutants) if pollutants else "Air pollution"
    correlation = result.correlation_evidence
    event = {
        # Candidate identity only. A future Coordinator/DB-backed incident
        # adapter will supply the final incident ID after grouping/routing.
        "id": anomaly.detection_id,
        "type": "air_pollution",
        "title": f"{pollutant_label} anomaly",
        "description": (
            result.plan.summary
            if result.plan is not None and result.plan.summary
            else anomaly.explanation
        ),
        "latitude": anomaly.location.latitude,
        "longitude": anomaly.location.longitude,
        "anomaly": anomaly.model_dump(mode="json"),
        "spatial_context": (
            candidate.spatial_context.model_dump(mode="json")
            if candidate.spatial_context is not None
            else None
        ),
        "correlation_evidence": (
            {
                "candidate_match": correlation.candidate_match,
                "duplicate_kind": correlation.duplicate_kind,
                "temporal_distance_seconds": correlation.temporal_distance_seconds,
                "spatial_distance_km": correlation.spatial_distance_km,
                "matching_signals": correlation.matching_signals,
                "conflicting_signals": correlation.conflicting_signals,
                "shared_geographic_features": correlation.shared_geographic_features,
                "limitations": correlation.limitations,
            }
            if correlation is not None
            else None
        ),
    }
    if result.plan is not None:
        event["pollution_response_plan"] = result.plan.model_dump(mode="json")
        event["planning_status"] = result.plan.status
    if result.transport_prediction is not None:
        event["air_pollution_transport"] = (
            result.transport_prediction.spatial_output.model_dump(mode="json")
        )
    return event


def attach_air_pollution_state(response: dict, snapshot: AirPollutionRuntimeSnapshot) -> dict:
    """Add independent pollution state without changing fire pipeline semantics."""
    events = list(response.get("events") or [])
    for item in snapshot.events:
        event = build_air_pollution_event(item)
        event["air_pollution_runtime"] = {
            "status": snapshot.status,
            "stale": snapshot.stale,
            "last_successful_collection_at": (
                snapshot.last_successful_collection_at.isoformat()
                if snapshot.last_successful_collection_at
                else None
            ),
        }
        events.append(event)
    metadata = dict(response.get("metadata") or {})
    services = dict(metadata.get("services") or {})
    services["air_pollution"] = {
        "status": snapshot.status,
        "source": "Israeli Ministry of Environmental Protection air monitoring",
        "last_attempted_at": (
            snapshot.last_attempted_at.isoformat() if snapshot.last_attempted_at else None
        ),
        "last_successful_collection_at": (
            snapshot.last_successful_collection_at.isoformat()
            if snapshot.last_successful_collection_at
            else None
        ),
        "stale": snapshot.stale,
        "observation_count": snapshot.observation_count,
        "excluded_count": snapshot.excluded_count,
        "errors": snapshot.errors,
    }
    metadata["services"] = services

    fire_status = metadata.get("collection_status")
    if fire_status == "failed" and snapshot.status in {"success", "partial"}:
        metadata["collection_status"] = "partial_service_failure"
    elif snapshot.status == "failed":
        if events or fire_status == "success":
            metadata["collection_status"] = "partial_service_failure"
    elif snapshot.status == "partial" and fire_status == "success":
        metadata["collection_status"] = "partial_service_failure"
    return {**response, "metadata": metadata, "events": events}
