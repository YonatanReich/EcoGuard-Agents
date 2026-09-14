"""Pure Air Pollution candidate correlation and supporting evidence."""

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Literal

from pydantic import Field, computed_field, model_validator

from agents.air_pollution_anomaly_schemas import AnomalyContract, AirPollutionAnomaly
from agents.air_pollution_spatial_schemas import (
    PollutionSpatialContext,
    SpatiallyEnrichedAirPollutionAnomaly,
)


class PollutionCorrelationCandidate(AnomalyContract):
    """Original anomaly/evidence plus optional geographic context, unchanged."""

    anomaly: AirPollutionAnomaly
    spatial_context: PollutionSpatialContext | None = None

    @model_validator(mode="after")
    def _consistent_location(self) -> "PollutionCorrelationCandidate":
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
        return [self.anomaly.pollutant]

    @computed_field
    @property
    def pollutant_categories(self) -> list[str]:
        pollutant = self.anomaly.pollutant
        return ["particulate_matter" if pollutant in {"PM2.5", "PM10"} else pollutant]

    @computed_field
    @property
    def time_bucket_utc(self) -> datetime:
        observed = self.anomaly.observed_at.astimezone(timezone.utc)
        return observed.replace(
            minute=(observed.minute // 30) * 30, second=0, microsecond=0
        )

    @computed_field
    @property
    def station_channels(self) -> list[tuple[str, str, str]]:
        return [(self.anomaly.provider, self.anomaly.station_id, self.anomaly.channel_id)]

    @computed_field
    @property
    def evidence_references(self) -> list[tuple[str, str]]:
        evidence = self.anomaly.baseline_evidence
        return [
            ("detector_rule", self.anomaly.detector_rule_version),
            ("baseline_version", str(evidence.version.baseline_version_id)),
            ("baseline_content_sha256", evidence.version.content_sha256),
        ]


class PollutionCorrelationPolicy(AnomalyContract):
    version: Literal["engineering-v1"] = "engineering-v1"
    maximum_minutes: float = Field(default=30.0, gt=0, strict=True)
    maximum_distance_km: float = Field(default=5.0, gt=0, strict=True)
    near_duplicate_seconds: float = Field(default=60.0, ge=0, strict=True)
    near_duplicate_distance_km: float = Field(default=0.1, ge=0, strict=True)

    @model_validator(mode="after")
    def _nested_limits(self) -> "PollutionCorrelationPolicy":
        if self.near_duplicate_seconds > self.maximum_minutes * 60:
            raise ValueError("duplicate time limit exceeds matching limit")
        if self.near_duplicate_distance_km > self.maximum_distance_km:
            raise ValueError("duplicate distance limit exceeds matching limit")
        return self


class PollutionCorrelationResult(AnomalyContract):
    left: PollutionCorrelationCandidate
    right: PollutionCorrelationCandidate
    policy: PollutionCorrelationPolicy
    candidate_match: bool
    duplicate_kind: Literal[
        "exact", "same_station_observation", "near_duplicate_candidate", "none"
    ]
    temporal_distance_seconds: float = Field(ge=0)
    spatial_distance_km: float = Field(ge=0)
    matching_signals: list[str]
    conflicting_signals: list[str]
    shared_geographic_features: list[str]
    evidence_references: list[tuple[str, str]]
    limitations: list[str]


def correlation_candidate(
    event: AirPollutionAnomaly | SpatiallyEnrichedAirPollutionAnomaly,
) -> PollutionCorrelationCandidate:
    """Prepare an anomaly for comparison without fetching or persisting data."""

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
    for category in (
        "nearby_settlements",
        "nearby_roads",
        "nearby_hospitals",
        "nearby_police_stations",
        "nearby_fire_stations",
    ):
        for item in getattr(context, category):
            if item.osm_id is not None and item.osm_type:
                identity = (item.osm_type, item.osm_id)
            elif item.name and item.latitude is not None and item.longitude is not None:
                identity = (item.name, item.latitude, item.longitude)
            else:
                continue
            keys.add(repr((context.source, category, identity)))
    return keys


def compare_pollution_candidates(
    left: PollutionCorrelationCandidate,
    right: PollutionCorrelationCandidate,
    *,
    policy: PollutionCorrelationPolicy | None = None,
) -> PollutionCorrelationResult:
    """Evaluate supporting proximity signals without creating an incident."""

    left = PollutionCorrelationCandidate.model_validate(
        left.model_dump(round_trip=True)
    )
    right = PollutionCorrelationCandidate.model_validate(
        right.model_dump(round_trip=True)
    )
    policy = PollutionCorrelationPolicy.model_validate(
        (policy or PollutionCorrelationPolicy()).model_dump()
    )
    a, b = left.anomaly, right.anomaly
    seconds = abs((a.observed_at - b.observed_at).total_seconds())
    lat_a, lat_b = radians(a.location.latitude), radians(b.location.latitude)
    delta_lat = lat_b - lat_a
    delta_lon = radians(b.location.longitude - a.location.longitude)
    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )
    distance = 6371.0 * 2 * asin(sqrt(min(1.0, max(0.0, haversine))))

    matches: list[str] = []
    conflicts: list[str] = []
    temporal = seconds <= policy.maximum_minutes * 60
    spatial = distance <= policy.maximum_distance_km
    (matches if temporal else conflicts).append(
        "within_time_window" if temporal else "outside_time_window"
    )
    (matches if spatial else conflicts).append(
        "within_distance_window" if spatial else "outside_distance_window"
    )
    same_pollutant = a.pollutant == b.pollutant
    compatible = bool(set(left.pollutant_categories) & set(right.pollutant_categories))
    if same_pollutant:
        matches.append("same_pollutant")
    elif compatible:
        matches.append("compatible_particulate_family")
    else:
        conflicts.append("pollutant_incompatible")

    shared_station = (a.provider, a.station_id) == (b.provider, b.station_id)
    shared_channel = shared_station and a.channel_id == b.channel_id
    if shared_station:
        matches.append("shared_provider_station")
    if shared_channel:
        matches.append("shared_station_channel")
    shared_features = sorted(_feature_keys(left) & _feature_keys(right))
    if shared_features:
        matches.append("overlapping_geographic_context")

    exact = left == right
    if a.detection_id == b.detection_id and a != b:
        conflicts.append("detection_id_reused_with_different_content")
    candidate_match = exact or (temporal and spatial and compatible)
    near = (
        seconds <= policy.near_duplicate_seconds
        and distance <= policy.near_duplicate_distance_km
    )
    duplicate = "none"
    if exact:
        duplicate = "exact"
        matches.append("identical_input")
    elif candidate_match and same_pollutant and near:
        duplicate = (
            "same_station_observation"
            if shared_channel and seconds == 0
            else "near_duplicate_candidate"
        )

    evidence_references = sorted(
        set(left.evidence_references) | set(right.evidence_references)
    )
    limitations = [
        "Engineering candidate evidence only; no causation or confirmed common event.",
        "Inputs and detector/baseline evidence are retained; nothing is merged or discarded.",
        "Shared nearby features do not establish exposure or pollution origin.",
        "No severity, emergency, incident, transport, or response decision is produced.",
    ]
    if any(
        candidate.spatial_context is None
        or candidate.spatial_context.status != "success"
        for candidate in (left, right)
    ):
        limitations.append(
            "Geographic context is absent, partial, or unavailable; missing overlap is not negative evidence."
        )
    return PollutionCorrelationResult(
        left=left,
        right=right,
        policy=policy,
        candidate_match=candidate_match,
        duplicate_kind=duplicate,
        temporal_distance_seconds=seconds,
        spatial_distance_km=distance,
        matching_signals=matches,
        conflicting_signals=conflicts,
        shared_geographic_features=shared_features,
        evidence_references=evidence_references,
        limitations=limitations,
    )
