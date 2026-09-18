"""GeoJSON-shaped WGS84 output for pollution transport screening.

The output is provider-neutral and contains no database integration. Geometry
coordinates use GeoJSON order ``[longitude, latitude]`` in EPSG:4326. Future
metric PostGIS operations must use ``geography`` or a suitable projected CRS;
plain EPSG:4326 geometry distances are angular degrees, not metres.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import asin, atan2, cos, degrees, radians, sin
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from ecoguard.detectors.air_pollution.schemas import ContractModel, GeographicCoordinate
from ecoguard.detectors.air_pollution.spatial_schemas import SettlementContextStatus
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import (
    AngularDifferenceDegrees,
    DirectionDegrees,
    NonNegativeFloat,
    PositiveRank,
    PotentialDownwindRelevance,
    RelevanceScore,
    SettlementExclusionReason,
    SignedFloat,
    TransportCorridorMethod,
    TransportDataStatus,
    TransportTimeMethod,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_corridor import (
    CorridorHalfAngleDegrees,
    PositiveDistanceMetres,
    TransportCorridorScreeningResult,
)
from ecoguard.analyzers.non_emergency.air_pollution.transport_geometry import (
    CoordinateInput,
    MEAN_EARTH_RADIUS_M,
)


LongitudeDegrees = Annotated[float, Field(ge=-180, le=180, strict=True)]
LatitudeDegrees = Annotated[float, Field(ge=-90, le=90, strict=True)]
ArcSegmentCount = Annotated[int, Field(ge=1, strict=True)]
LongitudeLatitude: TypeAlias = tuple[LongitudeDegrees, LatitudeDegrees]
CorridorInput: TypeAlias = TransportCorridorScreeningResult | Mapping[str, object]


class DatelineSpanningGeometryError(ValueError):
    """Raised when serialized linework would jump across the antimeridian."""


class GeoJSONPoint(ContractModel):
    type: Literal["Point"] = "Point"
    coordinates: LongitudeLatitude


class GeoJSONLineString(ContractModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[LongitudeLatitude] = Field(min_length=2)


class GeoJSONPolygon(ContractModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[LongitudeLatitude]] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def validate_exterior_ring(self):
        ring = self.coordinates[0]
        if len(ring) < 4:
            raise ValueError("polygon exterior ring requires at least four coordinates")
        if ring[0] != ring[-1]:
            raise ValueError("polygon exterior ring must be closed")
        if len(set(ring[:-1])) < 3:
            raise ValueError("polygon exterior ring requires three distinct coordinates")
        return self


class SpatialReferenceMetadata(ContractModel):
    """Explicit CRS/order information and future PostGIS adapter guidance."""

    srid: Literal[4326] = 4326
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    datum: Literal["WGS84"] = "WGS84"
    coordinate_order: Literal["longitude_latitude"] = "longitude_latitude"
    geometry_units: Literal["degrees"] = "degrees"
    geojson_to_geometry: Literal[
        "ST_SetSRID(ST_GeomFromGeoJSON(...), 4326)"
    ] = "ST_SetSRID(ST_GeomFromGeoJSON(...), 4326)"
    supported_future_predicates: tuple[
        Literal["ST_Intersects"],
        Literal["ST_DWithin"],
    ] = ("ST_Intersects", "ST_DWithin")
    supported_future_metric_functions: tuple[
        Literal["ST_DWithin"],
        Literal["ST_Distance"],
    ] = ("ST_DWithin", "ST_Distance")
    metric_distance_requirement: Literal[
        "Use PostGIS geography or an appropriate projected CRS for metre distances."
    ] = "Use PostGIS geography or an appropriate projected CRS for metre distances."


class SettlementSpatialOutput(ContractModel):
    """Existing settlement screening values plus a WGS84 point."""

    settlement_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    point: GeoJSONPoint
    inside_transport_corridor: bool
    rank: PositiveRank | None = None
    exclusion_reason: SettlementExclusionReason | None = None
    potential_downwind_relevance: PotentialDownwindRelevance
    relevance_score: RelevanceScore
    geodesic_distance_m: NonNegativeFloat
    bearing_from_origin_deg: DirectionDegrees
    angular_difference_deg: AngularDifferenceDegrees
    along_wind_distance_m: SignedFloat
    crosswind_distance_m: NonNegativeFloat
    kinematic_advection_time_seconds: NonNegativeFloat | None = None
    transport_time_method: TransportTimeMethod | None = None
    transport_time_assumptions: list[str] = Field(default_factory=list)
    exposure_not_confirmed: Literal[True] = True


class PollutionTransportSpatialOutput(ContractModel):
    """Deterministic output ready for frontend or future PostGIS adapters."""

    output_kind: Literal["estimated_transport_screening_geometry"] = (
        "estimated_transport_screening_geometry"
    )
    data_status: TransportDataStatus
    spatial_reference: SpatialReferenceMetadata = Field(
        default_factory=SpatialReferenceMetadata
    )
    origin: GeoJSONPoint
    centerline: GeoJSONLineString | None = None
    corridor_polygon: GeoJSONPolygon | None = None
    downwind_to_direction_deg: DirectionDegrees | None = None
    corridor_method: TransportCorridorMethod
    corridor_half_angle_deg: CorridorHalfAngleDegrees
    max_screening_distance_m: PositiveDistanceMetres
    direction_stddev_deg: NonNegativeFloat | None = None
    arc_segment_count: ArcSegmentCount
    dateline_handling: Literal["reject_longitude_discontinuity"] = (
        "reject_longitude_discontinuity"
    )
    settlements: list[SettlementSpatialOutput] = Field(default_factory=list)
    settlement_context: SettlementContextStatus | None = None
    limitations: list[str] = Field(min_length=1)
    exposure_not_confirmed: Literal[True] = True

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("limitations cannot contain blank entries")
        return stripped

    @model_validator(mode="after")
    def validate_availability(self):
        complete_geometry = (
            self.centerline is not None
            and self.corridor_polygon is not None
            and self.downwind_to_direction_deg is not None
        )
        any_geometry = (
            self.centerline is not None
            or self.corridor_polygon is not None
            or self.downwind_to_direction_deg is not None
        )
        if self.data_status == "unavailable":
            if any_geometry or self.settlements:
                raise ValueError(
                    "unavailable spatial output cannot contain corridor geometry or settlements"
                )
        elif not complete_geometry:
            raise ValueError(
                "available spatial output requires centerline and corridor polygon"
            )
        return self


class _DestinationInput(ContractModel):
    origin: GeographicCoordinate
    bearing_deg: DirectionDegrees
    distance_m: PositiveDistanceMetres


class _SectorInput(ContractModel):
    origin: GeographicCoordinate
    downwind_to_direction_deg: DirectionDegrees
    corridor_half_angle_deg: CorridorHalfAngleDegrees
    max_screening_distance_m: PositiveDistanceMetres
    arc_segment_count: ArcSegmentCount


class _ArcDiscretizationInput(ContractModel):
    arc_segment_count: ArcSegmentCount


def _validated_coordinate(value: CoordinateInput) -> GeographicCoordinate:
    payload = value.model_dump() if isinstance(value, GeographicCoordinate) else value
    return GeographicCoordinate.model_validate(payload)


def _longitude_latitude(point: GeographicCoordinate) -> LongitudeLatitude:
    return point.longitude, point.latitude


def destination_coordinate(
    origin: CoordinateInput,
    bearing_deg: float,
    distance_m: float,
) -> GeographicCoordinate:
    """Return a spherical great-circle destination with normalized longitude."""

    values = _DestinationInput(
        origin=_validated_coordinate(origin),
        bearing_deg=bearing_deg,
        distance_m=distance_m,
    )
    latitude_1 = radians(values.origin.latitude)
    longitude_1 = radians(values.origin.longitude)
    bearing = radians(values.bearing_deg)
    angular_distance = values.distance_m / MEAN_EARTH_RADIUS_M

    latitude_2_argument = (
        sin(latitude_1) * cos(angular_distance)
        + cos(latitude_1) * sin(angular_distance) * cos(bearing)
    )
    latitude_2 = asin(min(1.0, max(-1.0, latitude_2_argument)))
    longitude_2 = longitude_1 + atan2(
        sin(bearing) * sin(angular_distance) * cos(latitude_1),
        cos(angular_distance) - sin(latitude_1) * sin(latitude_2),
    )
    normalized_longitude = (degrees(longitude_2) + 540.0) % 360.0 - 180.0
    return GeographicCoordinate(
        latitude=degrees(latitude_2),
        longitude=normalized_longitude,
    )


def _reject_longitude_discontinuity(
    coordinates: list[LongitudeLatitude],
) -> None:
    if any(
        abs(right[0] - left[0]) > 180.0
        for left, right in zip(coordinates, coordinates[1:])
    ):
        raise DatelineSpanningGeometryError(
            "dateline-spanning linework is not supported by this serializer"
        )


def build_centerline(
    origin: CoordinateInput,
    downwind_to_direction_deg: float,
    max_screening_distance_m: float,
) -> GeoJSONLineString:
    """Build the diagnostic origin-to-downwind endpoint LineString."""

    origin_point = _validated_coordinate(origin)
    endpoint = destination_coordinate(
        origin_point,
        downwind_to_direction_deg,
        max_screening_distance_m,
    )
    coordinates = [_longitude_latitude(origin_point), _longitude_latitude(endpoint)]
    _reject_longitude_discontinuity(coordinates)
    return GeoJSONLineString(coordinates=coordinates)


def build_sector_polygon(
    origin: CoordinateInput,
    downwind_to_direction_deg: float,
    corridor_half_angle_deg: float,
    max_screening_distance_m: float,
    arc_segment_count: int,
) -> GeoJSONPolygon:
    """Build a closed sector using a caller-selected number of arc segments."""

    values = _SectorInput(
        origin=_validated_coordinate(origin),
        downwind_to_direction_deg=downwind_to_direction_deg,
        corridor_half_angle_deg=corridor_half_angle_deg,
        max_screening_distance_m=max_screening_distance_m,
        arc_segment_count=arc_segment_count,
    )
    origin_coordinate = _longitude_latitude(values.origin)
    counterclockwise_boundary = (
        values.downwind_to_direction_deg - values.corridor_half_angle_deg
    )
    angular_step = 2.0 * values.corridor_half_angle_deg / values.arc_segment_count
    arc_coordinates = [
        _longitude_latitude(
            destination_coordinate(
                values.origin,
                (counterclockwise_boundary + index * angular_step) % 360.0,
                values.max_screening_distance_m,
            )
        )
        for index in range(values.arc_segment_count + 1)
    ]
    exterior_ring = [origin_coordinate, *arc_coordinates, origin_coordinate]
    _reject_longitude_discontinuity(exterior_ring)
    return GeoJSONPolygon(coordinates=[exterior_ring])


def _validated_corridor(value: CorridorInput) -> TransportCorridorScreeningResult:
    payload = (
        value.model_dump()
        if isinstance(value, TransportCorridorScreeningResult)
        else value
    )
    return TransportCorridorScreeningResult.model_validate(payload)


def prepare_transport_spatial_output(
    analysis_origin_coordinates: CoordinateInput,
    corridor_result: CorridorInput,
    *,
    arc_segment_count: int,
    settlement_context: SettlementContextStatus | None = None,
) -> PollutionTransportSpatialOutput:
    """Serialize existing corridor/settlement results without recalculation."""

    origin = _validated_coordinate(analysis_origin_coordinates)
    corridor = _validated_corridor(corridor_result)
    segment_count = _ArcDiscretizationInput(
        arc_segment_count=arc_segment_count,
    ).arc_segment_count
    common = {
        "data_status": corridor.data_status,
        "origin": GeoJSONPoint(coordinates=_longitude_latitude(origin)),
        "corridor_method": corridor.parameters.corridor_method,
        "corridor_half_angle_deg": corridor.parameters.corridor_half_angle_deg,
        "max_screening_distance_m": corridor.parameters.max_screening_distance_m,
        "direction_stddev_deg": corridor.parameters.direction_stddev_deg,
        "arc_segment_count": segment_count,
        "settlement_context": settlement_context,
        "limitations": [
            *corridor.limitations,
            "Sector geometry is a screening visualization, not a physical plume.",
        ],
    }
    if corridor.data_status == "unavailable":
        return PollutionTransportSpatialOutput(**common)

    assert corridor.downwind_to_direction_deg is not None
    settlement_outputs = [
        SettlementSpatialOutput(
            settlement_id=item.settlement_id,
            name=item.name,
            point=GeoJSONPoint(
                coordinates=(item.coordinates.longitude, item.coordinates.latitude)
            ),
            inside_transport_corridor=item.inside_transport_corridor,
            rank=item.rank,
            exclusion_reason=item.exclusion_reason,
            potential_downwind_relevance=item.potential_downwind_relevance,
            relevance_score=item.relevance_score,
            geodesic_distance_m=item.geodesic_distance_m,
            bearing_from_origin_deg=item.bearing_from_origin_deg,
            angular_difference_deg=item.angular_difference_deg,
            along_wind_distance_m=item.along_wind_distance_m,
            crosswind_distance_m=item.crosswind_distance_m,
            kinematic_advection_time_seconds=item.kinematic_advection_time_seconds,
            transport_time_method=item.transport_time_method,
            transport_time_assumptions=item.transport_time_assumptions,
        )
        for item in corridor.settlement_results
    ]
    return PollutionTransportSpatialOutput(
        **common,
        downwind_to_direction_deg=corridor.downwind_to_direction_deg,
        centerline=build_centerline(
            origin,
            corridor.downwind_to_direction_deg,
            corridor.parameters.max_screening_distance_m,
        ),
        corridor_polygon=build_sector_polygon(
            origin,
            corridor.downwind_to_direction_deg,
            corridor.parameters.corridor_half_angle_deg,
            corridor.parameters.max_screening_distance_m,
            segment_count,
        ),
        settlements=settlement_outputs,
    )
