"""EA-311 offline candidate comparison for a future Coordinator.

Engineering policy v1 defaults: 30 minutes / 5 km for plausible relatedness;
60 seconds / 0.1 km for near-duplicate candidates with the same pollutant set.
These are configurable retrieval heuristics, not health rules, plume models or
calibrated probabilities. Buckets are indexing hints ONLY: comparisons always
use exact timestamps and coordinates, including across bucket boundaries.
Both complete inputs are retained; no merging, evidence deletion or causation.
"""

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Literal

from pydantic import Field, computed_field, model_validator

from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly, ContractModel
from agents.air_pollution_spatial_schemas import (
    PollutionSpatialContext, SpatiallyEnrichedAirPollutionAnomaly,
)


class PollutionCorrelationCandidate(ContractModel):
    """Original detection/provenance plus optional EA-310 context.

    Identity, time, location, severity, confidence, measurements and sources
    remain authoritative in ``anomaly``. Derived indexing fields cannot drift
    from them. No pollutant is inferred for degraded observations.
    Use ``model_dump_json(round_trip=True)`` for persistence/round trips;
    ordinary serialization additionally includes read-only derived hints.
    """

    anomaly: AirPollutionAnomaly
    spatial_context: PollutionSpatialContext | None = None

    @model_validator(mode="after")
    def consistent_location(self):
        if self.spatial_context and self.spatial_context.location != self.anomaly.location:
            raise ValueError("spatial context must belong to the anomaly location")
        return self

    @computed_field
    @property
    def hazard_type(self) -> Literal["air_pollution"]:
        return "air_pollution"

    @computed_field
    @property
    def pollutants(self) -> list[str]:
        return sorted({item.pollutant for item in self.anomaly.pollutant_observations})

    @computed_field
    @property
    def pollutant_categories(self) -> list[str]:
        # Only this explicit compatibility family is currently supported.
        return sorted({"particulate_matter" if p in {"PM2.5", "PM10"} else p for p in self.pollutants})

    @computed_field
    @property
    def time_bucket_utc(self) -> datetime:
        observed = self.anomaly.observed_at.astimezone(timezone.utc)
        return observed.replace(minute=(observed.minute // 30) * 30, second=0, microsecond=0)

    @computed_field
    @property
    def station_channels(self) -> list[tuple[str, str, str | None]]:
        identities = set()
        for source in self.anomaly.sources:
            station = source.metadata.get("station_id")
            channel = source.metadata.get("channel_id")
            if isinstance(station, str) and station.strip():
                identities.add((source.source_id, station, channel if isinstance(channel, str) and channel.strip() else None))
        return sorted(identities, key=lambda item: (item[0], item[1], item[2] or ""))

    @computed_field
    @property
    def evidence_references(self) -> list[tuple[str, str]]:
        return sorted({(item.source_id, item.evidence_id) for item in self.anomaly.supporting_evidence})


class PollutionCorrelationPolicy(ContractModel):
    version: Literal["engineering-v1"] = "engineering-v1"
    maximum_minutes: float = Field(default=30.0, gt=0, strict=True)
    maximum_distance_km: float = Field(default=5.0, gt=0, strict=True)
    near_duplicate_seconds: float = Field(default=60.0, ge=0, strict=True)
    near_duplicate_distance_km: float = Field(default=0.1, ge=0, strict=True)

    @model_validator(mode="after")
    def nested_limits(self):
        if self.near_duplicate_seconds > self.maximum_minutes * 60:
            raise ValueError("duplicate time limit exceeds matching limit")
        if self.near_duplicate_distance_km > self.maximum_distance_km:
            raise ValueError("duplicate distance limit exceeds matching limit")
        return self


class PollutionCorrelationResult(ContractModel):
    left: PollutionCorrelationCandidate
    right: PollutionCorrelationCandidate
    policy: PollutionCorrelationPolicy
    candidate_match: bool
    duplicate_kind: Literal["exact", "same_station_observation", "near_duplicate_candidate", "none"]
    temporal_distance_seconds: float = Field(ge=0)
    spatial_distance_km: float = Field(ge=0)
    matching_signals: list[str]
    conflicting_signals: list[str]
    shared_geographic_features: list[str]
    limitations: list[str]


def correlation_candidate(
    event: AirPollutionAnomaly | SpatiallyEnrichedAirPollutionAnomaly,
) -> PollutionCorrelationCandidate:
    """Prepare raw or enriched anomalies without fetching any context."""
    if isinstance(event, SpatiallyEnrichedAirPollutionAnomaly):
        payload = event.model_dump()
    elif isinstance(event, AirPollutionAnomaly):
        payload = {"anomaly": event.model_dump()}
    else:
        raise TypeError("expected AirPollutionAnomaly or its spatial enrichment")
    return PollutionCorrelationCandidate.model_validate(payload)


def _feature_keys(candidate: PollutionCorrelationCandidate) -> set[str]:
    context = candidate.spatial_context
    if not context or context.status == "unavailable" or not context.source:
        return set()
    keys = set()
    for category in ("nearby_settlements", "nearby_roads", "nearby_hospitals",
                     "nearby_police_stations", "nearby_fire_stations"):
        for item in getattr(context, category):
            # Names alone are not identities; absent OSM IDs require identical
            # names AND representative coordinates for this supporting signal.
            if item.osm_id is not None and item.osm_type:
                identity = (item.osm_type, item.osm_id)
            elif item.name and item.latitude is not None and item.longitude is not None:
                identity = (item.name, item.latitude, item.longitude)
            else:
                continue
            keys.add(repr((context.source, category, identity)))
    return keys


def compare_pollution_candidates(
    left: PollutionCorrelationCandidate, right: PollutionCorrelationCandidate,
    *, policy: PollutionCorrelationPolicy | None = None,
) -> PollutionCorrelationResult:
    """Compare exact time/location; context never overrides a failed gate.

    Existing distance helpers are private fire/ML methods. A local standard
    Haversine avoids importing those agents and their provider dependencies.
    """
    left = PollutionCorrelationCandidate.model_validate(left.model_dump(round_trip=True))
    right = PollutionCorrelationCandidate.model_validate(right.model_dump(round_trip=True))
    policy = PollutionCorrelationPolicy.model_validate((policy or PollutionCorrelationPolicy()).model_dump())
    a, b = left.anomaly, right.anomaly
    seconds = abs((a.observed_at - b.observed_at).total_seconds())
    lat_a, lat_b = radians(a.location.latitude), radians(b.location.latitude)
    delta_lat = lat_b - lat_a
    delta_lon = radians(b.location.longitude - a.location.longitude)
    haversine = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    distance = 6371.0 * 2 * asin(sqrt(min(1.0, max(0.0, haversine))))
    matches, conflicts = [], []
    temporal = seconds <= policy.maximum_minutes * 60
    spatial = distance <= policy.maximum_distance_km
    (matches if temporal else conflicts).append("within_time_window" if temporal else "outside_time_window")
    (matches if spatial else conflicts).append("within_distance_window" if spatial else "outside_distance_window")
    shared_pollutants = set(left.pollutants) & set(right.pollutants)
    compatible = bool(set(left.pollutant_categories) & set(right.pollutant_categories))
    if shared_pollutants:
        matches.append("same_pollutant")
    elif compatible:
        matches.append("compatible_particulate_family")
    else:
        conflicts.append("pollutant_missing_or_incompatible")
    stations_a = {(source, station) for source, station, _ in left.station_channels}
    stations_b = {(source, station) for source, station, _ in right.station_channels}
    shared_station = bool(stations_a & stations_b)
    if shared_station:
        matches.append("shared_provider_station")
    if {s.source_id for s in a.sources} & {s.source_id for s in b.sources}:
        matches.append("shared_source")
    shared_features = sorted(_feature_keys(left) & _feature_keys(right))
    if shared_features:
        matches.append("overlapping_geographic_context")
    exact = left == right
    if a.detection_id == b.detection_id and a != b:
        conflicts.append("detection_id_reused_with_different_content")
    candidate_match = exact or (temporal and spatial and compatible)
    same_set = bool(left.pollutants) and left.pollutants == right.pollutants
    near = seconds <= policy.near_duplicate_seconds and distance <= policy.near_duplicate_distance_km
    duplicate = "none"
    if exact:
        duplicate = "exact"
        matches.append("identical_input")
    elif candidate_match and same_set and near:
        # A shared station does not erase conflicting channel identities.
        shared_channel = bool(set(left.station_channels) & set(right.station_channels))
        if shared_station and shared_channel and seconds == 0:
            duplicate = "same_station_observation"
        else:
            duplicate = "near_duplicate_candidate"
    limitations = [
        "Engineering candidate evidence only; no calibrated probability, causation or confirmed common event.",
        "No inputs are merged or discarded; repeated observations may contain revisions.",
        "Shared nearby facilities do not establish exposure, availability or pollution origin.",
        "Severity and detection confidence are preserved, not reinterpreted as correlation confidence.",
    ]
    if any(c.spatial_context is None or c.spatial_context.status != "success" for c in (left, right)):
        limitations.append("Geographic context is absent, partial or unavailable; missing overlap is not negative evidence.")
    if not left.pollutants or not right.pollutants:
        limitations.append("No pollutant was inferred for missing measurements.")
    return PollutionCorrelationResult(
        left=left, right=right, policy=policy, candidate_match=candidate_match,
        duplicate_kind=duplicate, temporal_distance_seconds=seconds,
        spatial_distance_km=distance, matching_signals=matches, conflicting_signals=conflicts,
        shared_geographic_features=shared_features, limitations=limitations,
    )
