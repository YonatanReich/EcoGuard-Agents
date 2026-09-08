"""Enrich an existing anomaly using one existing geospatial lookup, or its result.

No detector/network coupling, additional provider, retries, distance inference,
population estimation, source attribution, or operational decisions are added.
Unknown future fields are not promoted into the normalized context. Malformed
features are counted and omitted individually. Provider exception text is never
copied to output because it may contain request URLs or credentials.
"""

from collections.abc import Mapping
from datetime import timezone
from typing import Protocol

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly, GeographicCoordinate
from agents.air_pollution_spatial_schemas import (
    NearbyGeographicFeature, PollutionSpatialContext, SpatiallyEnrichedAirPollutionAnomaly,
)
from agents.geospatial_context_agent import GeospatialContextAgent

LAYERS = (
    "nearby_settlements", "nearby_roads", "nearby_hospitals",
    "nearby_police_stations", "nearby_fire_stations",
)
LIMITATIONS = [
    "Nearby features do not establish exposure, pollution source, or operational availability.",
    "Coordinates may be representative OSM centers; road geometry is not provided.",
    "Population tags, when supplied, are source attributes, not affected-person counts.",
    "Terrain, region, vegetation, water distance, green areas and water sources are not collected by the current combined lookup.",
    "Industrial sites, schools, elderly-care facilities and population density are not collected.",
]


class GeospatialProvider(Protocol):
    def fetch_nearby_context(self, latitude: float, longitude: float, radius_km: float = 2) -> dict: ...


class AirPollutionSpatialEnricher:
    """Inject a compatible provider or pass the existing agent's full envelope.

    Invalid anomaly coordinates/radius raise validation errors before network
    access. A valid anomaly survives provider failure unchanged. An envelope
    for a different coordinate/radius is rejected as unavailable context.
    """

    def __init__(self, geospatial_provider: GeospatialProvider | None = None):
        self.provider = geospatial_provider if geospatial_provider is not None else GeospatialContextAgent()

    def enrich(
        self, anomaly: AirPollutionAnomaly, *, radius_km: float = 2.0,
        geospatial_context: Mapping | None = None,
    ) -> SpatiallyEnrichedAirPollutionAnomaly:
        # Revalidate even model_copy/model_construct inputs; never query invalid coordinates.
        validated = AirPollutionAnomaly.model_validate(anomaly.model_dump())
        context = PollutionSpatialContext(
            location=validated.location, lookup_radius_km=radius_km,
            status="unavailable", limitations=list(LIMITATIONS),
        )
        result = SpatiallyEnrichedAirPollutionAnomaly(anomaly=validated, spatial_context=context)
        if geospatial_context is None:
            try:
                geospatial_context = self.provider.fetch_nearby_context(
                    validated.location.latitude, validated.location.longitude, radius_km=radius_km,
                )
            except Exception:
                context.errors.append("geospatial_lookup_failed")
                return result
        if not isinstance(geospatial_context, Mapping):
            context.errors.append("malformed_geospatial_response")
            return result

        metadata = geospatial_context.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        source = metadata.get("data_source")
        context.source = source if isinstance(source, str) and source.strip() else None
        status = metadata.get("collection_status")
        context.provider_collection_status = status if isinstance(status, str) else None
        try:
            if metadata.get("timestamp") is not None:
                context.collected_at = TypeAdapter(AwareDatetime).validate_python(
                    metadata["timestamp"]
                ).astimezone(timezone.utc)
        except (ValidationError, ValueError):
            context.errors.append("invalid_collection_timestamp")
        missing = geospatial_context.get("missing_layers", [])
        if isinstance(missing, list) and all(isinstance(item, str) for item in missing):
            context.missing_layers = list(missing)
        else:
            context.errors.append("malformed_missing_layers")

        lookup = geospatial_context.get("location")
        if lookup is None:
            context.errors.append("lookup_location_not_provided")
        else:
            try:
                if not isinstance(lookup, Mapping):
                    raise ValueError("invalid location")
                point = GeographicCoordinate.model_validate({key: lookup.get(key) for key in ("latitude", "longitude")})
                if point != validated.location:
                    raise ValueError("different location")
                if "radius_km" in lookup:
                    checked_radius = PollutionSpatialContext(
                        location=point, lookup_radius_km=lookup["radius_km"], status="unavailable",
                    ).lookup_radius_km
                    if checked_radius != radius_km:
                        raise ValueError("different radius")
                else:
                    context.errors.append("lookup_radius_not_provided")
            except (ValidationError, ValueError):
                context.errors.append("invalid_or_mismatched_lookup_location")
                return result

        if status == "failed":
            context.errors.append("geospatial_lookup_failed")
            return result
        layers = geospatial_context.get("geospatial_context")
        if not isinstance(layers, Mapping):
            context.errors.append("missing_geospatial_layers")
            return result
        for layer in LAYERS:
            items = layers.get(layer)
            if not isinstance(items, list):
                context.errors.append(f"missing_or_malformed_layer:{layer}")
                continue
            accepted = []
            for item in items:
                try:
                    if not isinstance(item, Mapping):
                        raise ValueError("invalid feature")
                    fields = {key: value for key, value in item.items() if key in NearbyGeographicFeature.model_fields}
                    if not fields:
                        raise ValueError("no geographic attributes")
                    accepted.append(NearbyGeographicFeature.model_validate(fields))
                except (ValidationError, ValueError):
                    context.excluded_feature_counts[layer] = context.excluded_feature_counts.get(layer, 0) + 1
            setattr(context, layer, accepted)
        if context.source is None or context.collected_at is None:
            context.errors.append("incomplete_geographic_provenance")
        context.status = "success" if (
            status == "success" and not context.errors
            and not context.excluded_feature_counts and not context.missing_layers
        ) else "partial"
        return result
