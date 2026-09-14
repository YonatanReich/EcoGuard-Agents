"""Geographic context contracts for a detected Air Pollution anomaly.

Nearby features are context only: they do not establish exposure, pollution
origin, an affected area, availability, or an operational decision.
"""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from agents.air_pollution_anomaly_schemas import AnomalyContract, AirPollutionAnomaly
from services.air_quality_schemas import GeographicCoordinate


class NearbyGeographicFeature(AnomalyContract):
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
    def _coordinate_pair(self) -> "NearbyGeographicFeature":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("feature coordinates must be supplied together")
        return self


class PollutionSpatialContext(AnomalyContract):
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
    missing_layers: list[str] = Field(default_factory=list)
    excluded_feature_counts: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SpatiallyEnrichedAirPollutionAnomaly(AnomalyContract):
    """The original anomaly plus context, with no anomaly reassessment."""

    anomaly: AirPollutionAnomaly
    spatial_context: PollutionSpatialContext

    @model_validator(mode="after")
    def _same_location(self) -> "SpatiallyEnrichedAirPollutionAnomaly":
        if self.spatial_context.location != self.anomaly.location:
            raise ValueError("spatial context must belong to the anomaly location")
        return self
