"""EA-310 geographic context: proximity does not establish exposure or cause.

Collection -> detector -> AirPollutionAnomaly -> spatial enrichment -> future
Coordinator. The lookup radius is a search parameter, never an affected area.
OSM population tags are unverified source attributes, not affected-person counts.
"""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from agents.air_pollution_anomaly_schemas import (
    AirPollutionAnomaly, ContractModel, GeographicCoordinate,
)


class NearbyGeographicFeature(ContractModel):
    """Existing normalized OSM fields; coordinates may be representative centers."""

    name: str | None = None
    type: str | None = None
    ref: str | None = None
    osm_id: int | str | None = None
    osm_type: Literal["node", "way", "relation"] | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, strict=True)
    longitude: float | None = Field(default=None, ge=-180, le=180, strict=True)
    population: str | int | None = None
    distance_km: float | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("feature coordinates must be supplied together")
        return self


class PollutionSpatialContext(ContractModel):
    location: GeographicCoordinate
    lookup_radius_km: float = Field(gt=0, strict=True)
    status: Literal["success", "partial", "unavailable"]
    source: str | None = None
    collected_at: AwareDatetime | None = None
    provider_collection_status: str | None = None
    nearby_settlements: list[NearbyGeographicFeature] = Field(default_factory=list)
    nearby_roads: list[NearbyGeographicFeature] = Field(default_factory=list)
    nearby_hospitals: list[NearbyGeographicFeature] = Field(default_factory=list)
    nearby_police_stations: list[NearbyGeographicFeature] = Field(default_factory=list)
    nearby_fire_stations: list[NearbyGeographicFeature] = Field(default_factory=list)
    # Provider missing_layers includes both empty results and unsupported layers.
    missing_layers: list[str] = Field(default_factory=list)
    excluded_feature_counts: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SpatiallyEnrichedAirPollutionAnomaly(ContractModel):
    """Existing anomaly plus context; no reassessment, correlation or response."""

    anomaly: AirPollutionAnomaly
    spatial_context: PollutionSpatialContext
