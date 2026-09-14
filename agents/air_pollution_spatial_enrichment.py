"""Add shared geospatial context to a suspected Air Pollution anomaly."""

from collections.abc import Mapping
from datetime import timezone
from typing import Protocol

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from agents.air_pollution_anomaly_schemas import (
    AirPollutionAnomaly,
    AirPollutionDetectionResult,
)
from agents.air_pollution_spatial_schemas import (
    NearbyGeographicFeature,
    PollutionSpatialContext,
    SpatiallyEnrichedAirPollutionAnomaly,
)
from agents.geospatial_context_agent import GeospatialContextAgent
from services.air_quality_schemas import GeographicCoordinate

LAYERS = (
    "nearby_settlements",
    "nearby_roads",
    "nearby_hospitals",
    "nearby_police_stations",
    "nearby_fire_stations",
)
LIMITATIONS = [
    "Nearby features do not establish exposure, pollution source, or operational availability.",
    "Coordinates may be representative OpenStreetMap centers; road geometry is not provided.",
    "Population tags are source attributes, not affected-person counts.",
    "No affected area, transport, plume, severity, risk, or response conclusion is produced.",
]


class GeospatialProvider(Protocol):
    def fetch_nearby_context(
        self, latitude: float, longitude: float, radius_km: float = 2
    ) -> dict: ...


class AirPollutionSpatialEnricher:
    """Use Yonatan's shared geospatial provider or normalize supplied context."""

    def __init__(self, geospatial_provider: GeospatialProvider | None = None):
        self.provider = geospatial_provider or GeospatialContextAgent()

    def enrich_detection_result(
        self,
        result: AirPollutionDetectionResult,
        *,
        radius_km: float = 2.0,
        geospatial_context: Mapping | None = None,
    ) -> SpatiallyEnrichedAirPollutionAnomaly | None:
        """Pipeline gate: NORMAL and NOT_EVALUATED terminate before lookup."""

        validated = AirPollutionDetectionResult.model_validate(result.model_dump())
        if validated.status != "SUSPECTED_ANOMALY" or validated.anomaly is None:
            return None
        return self.enrich(
            validated.anomaly,
            radius_km=radius_km,
            geospatial_context=geospatial_context,
        )

    def enrich(
        self,
        anomaly: AirPollutionAnomaly,
        *,
        radius_km: float = 2.0,
        geospatial_context: Mapping | None = None,
    ) -> SpatiallyEnrichedAirPollutionAnomaly:
        validated = AirPollutionAnomaly.model_validate(anomaly.model_dump())
        context = PollutionSpatialContext(
            location=validated.location,
            lookup_radius_km=radius_km,
            status="unavailable",
            limitations=list(LIMITATIONS),
        )
        enriched = SpatiallyEnrichedAirPollutionAnomaly(
            anomaly=validated, spatial_context=context
        )
        if geospatial_context is None:
            try:
                geospatial_context = self.provider.fetch_nearby_context(
                    validated.location.latitude,
                    validated.location.longitude,
                    radius_km=radius_km,
                )
            except Exception:
                context.errors.append("geospatial_lookup_failed")
                return enriched
        if not isinstance(geospatial_context, Mapping):
            context.errors.append("malformed_geospatial_response")
            return enriched

        metadata = geospatial_context.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        source = metadata.get("data_source")
        context.source = source if isinstance(source, str) and source.strip() else None
        provider_status = metadata.get("collection_status")
        context.provider_collection_status = (
            provider_status if isinstance(provider_status, str) else None
        )
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

        if not self._lookup_matches(
            geospatial_context.get("location"), validated.location, radius_km
        ):
            context.errors.append("invalid_or_mismatched_lookup_location")
            return enriched
        if provider_status == "failed":
            context.errors.append("geospatial_lookup_failed")
            return enriched

        layers = geospatial_context.get("geospatial_context")
        if not isinstance(layers, Mapping):
            context.errors.append("missing_geospatial_layers")
            return enriched
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
                    fields = {
                        key: value
                        for key, value in item.items()
                        if key in NearbyGeographicFeature.model_fields
                    }
                    if not fields:
                        raise ValueError("no geographic attributes")
                    accepted.append(NearbyGeographicFeature.model_validate(fields))
                except (ValidationError, ValueError):
                    context.excluded_feature_counts[layer] = (
                        context.excluded_feature_counts.get(layer, 0) + 1
                    )
            setattr(context, layer, accepted)

        if context.source is None or context.collected_at is None:
            context.errors.append("incomplete_geographic_provenance")
        context.status = (
            "success"
            if provider_status == "success"
            and not context.errors
            and not context.excluded_feature_counts
            and not context.missing_layers
            else "partial"
        )
        return enriched

    @staticmethod
    def _lookup_matches(
        lookup: object,
        anomaly_location: GeographicCoordinate,
        radius_km: float,
    ) -> bool:
        try:
            if not isinstance(lookup, Mapping):
                return False
            point = GeographicCoordinate.model_validate(
                {key: lookup.get(key) for key in ("latitude", "longitude")}
            )
            checked = PollutionSpatialContext(
                location=point,
                lookup_radius_km=lookup.get("radius_km"),
                status="unavailable",
            )
            return point == anomaly_location and checked.lookup_radius_km == radius_km
        except (ValidationError, ValueError):
            return False
