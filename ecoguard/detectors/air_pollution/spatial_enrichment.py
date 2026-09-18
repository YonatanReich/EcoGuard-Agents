"""Add DB-backed geographic context to a suspected Air Pollution anomaly."""

from collections.abc import Callable, Mapping
from datetime import timezone
from typing import Protocol

from pydantic import AwareDatetime, TypeAdapter, ValidationError

from ecoguard.database.repositories.towns import (
    TownLookupResult,
    TownLookupStatus,
    nearby_towns,
)
from ecoguard.detectors.air_pollution.schemas import (
    AirPollutionAnomaly,
    AirPollutionDetectionResult,
)
from ecoguard.detectors.air_pollution.spatial_schemas import (
    NearbyGeographicFeature,
    PollutionSpatialContext,
    SettlementContextStatus,
    SpatiallyEnrichedAirPollutionAnomaly,
)
from ecoguard.shared.air_quality_schemas import GeographicCoordinate

OTHER_LAYERS = (
    "nearby_roads",
    "nearby_hospitals",
    "nearby_police_stations",
    "nearby_fire_stations",
)
LAYERS = ("nearby_settlements", *OTHER_LAYERS)
LIMITATIONS = [
    "Nearby features do not establish exposure, pollution source, or operational availability.",
    "Town outlines identify nearby settlements; stored town label points support the current point-based transport ranking semantics.",
    "No affected area, transport, plume, severity, risk, or response conclusion is produced.",
]


class GeospatialProvider(Protocol):
    def fetch_nearby_context(
        self, latitude: float, longitude: float, radius_km: float = 2
    ) -> dict: ...


TownLookup = Callable[..., TownLookupResult]


class AirPollutionSpatialEnricher:
    """Read settlements from PostGIS; optional providers supply other layers only."""

    def __init__(
        self,
        geospatial_provider: GeospatialProvider | None = None,
        *,
        town_lookup: TownLookup = nearby_towns,
    ):
        # Deliberately no default Overpass provider. Fire and the shared
        # geospatial service retain their existing behavior.
        self.provider = geospatial_provider
        self.town_lookup = town_lookup

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
            source="shared_postgis_towns",
            limitations=list(LIMITATIONS),
        )
        enriched = SpatiallyEnrichedAirPollutionAnomaly(
            anomaly=validated, spatial_context=context
        )
        self._add_towns(context, validated.location, radius_km)

        # An explicitly supplied provider/context may still contribute roads
        # and facilities. Its settlement layer is always ignored.
        provider_context = geospatial_context
        if provider_context is None and self.provider is not None:
            try:
                provider_context = self.provider.fetch_nearby_context(
                    validated.location.latitude,
                    validated.location.longitude,
                    radius_km=radius_km,
                )
            except Exception:
                context.errors.append("geospatial_other_layers_lookup_failed")
        if provider_context is not None:
            self._add_other_layers(
                context, provider_context, validated.location, radius_km
            )

        town_layer_available = (
            context.settlement_context is not None
            and context.settlement_context.status == "success"
        )
        other_layers_failed = any(
            error.startswith("geospatial_other_layers")
            or error.startswith("missing_or_malformed_layer")
            or error == "malformed_missing_layers"
            or error
            in {
                "malformed_geospatial_response",
                "invalid_or_mismatched_lookup_location",
                "missing_geospatial_layers",
            }
            for error in context.errors
        )
        context.status = (
            "success"
            if town_layer_available and not other_layers_failed
            else "partial"
            if town_layer_available or provider_context is not None
            else "unavailable"
        )
        return enriched

    def _add_towns(
        self,
        context: PollutionSpatialContext,
        location: GeographicCoordinate,
        radius_km: float,
    ) -> None:
        try:
            result = self.town_lookup(
                latitude=location.latitude,
                longitude=location.longitude,
                radius_m=radius_km * 1000.0,
            )
        except Exception:
            result = TownLookupResult(
                status=TownLookupStatus.UNAVAILABLE,
                reason="town_repository_unavailable",
            )
        succeeded = result.status in {
            TownLookupStatus.SUCCESS_WITH_RESULTS,
            TownLookupStatus.SUCCESS_EMPTY,
        }
        context.settlement_context = SettlementContextStatus(
            status="success" if succeeded else "unavailable",
            outcome=result.status.value,
            candidate_count=len(result.candidates),
            reason=result.reason,
        )
        context.provider_collection_status = result.status.value
        context.nearby_settlements = [
            NearbyGeographicFeature(
                name=item.name_he or item.name_en,
                type=item.place,
                ref=item.town_id,
                latitude=item.latitude,
                longitude=item.longitude,
                population=item.population,
                distance_km=item.distance_m / 1000.0,
            )
            for item in result.candidates
        ]
        if not succeeded:
            context.missing_layers.append("nearby_settlements")
            context.errors.append(result.reason or "town_repository_unavailable")

    def _add_other_layers(
        self,
        context: PollutionSpatialContext,
        response: object,
        anomaly_location: GeographicCoordinate,
        radius_km: float,
    ) -> None:
        if not isinstance(response, Mapping):
            context.errors.append("malformed_geospatial_response")
            return
        if not self._lookup_matches(response.get("location"), anomaly_location, radius_km):
            context.errors.append("invalid_or_mismatched_lookup_location")
            return
        metadata = response.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        if metadata.get("collection_status") == "failed":
            context.errors.append("geospatial_other_layers_lookup_failed")
            return
        missing = response.get("missing_layers", [])
        if isinstance(missing, list) and all(isinstance(item, str) for item in missing):
            context.missing_layers.extend(
                item for item in missing if item in OTHER_LAYERS
            )
        else:
            context.errors.append("malformed_missing_layers")
        try:
            if metadata.get("timestamp") is not None:
                context.collected_at = TypeAdapter(AwareDatetime).validate_python(
                    metadata["timestamp"]
                ).astimezone(timezone.utc)
        except (ValidationError, ValueError):
            context.errors.append("invalid_collection_timestamp")
        layers = response.get("geospatial_context")
        if not isinstance(layers, Mapping):
            context.errors.append("missing_geospatial_layers")
            return
        for layer in OTHER_LAYERS:
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
