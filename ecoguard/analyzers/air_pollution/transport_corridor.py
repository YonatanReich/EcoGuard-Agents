"""Deterministic wedge/sector screening for potential atmospheric transport.

This module applies caller-supplied geometry to EA-319 spatial rankings. The
corridor is not a physical plume, concentration, exposure, affected-area, or
probability model. How a caller selects the half-angle and maximum distance is
deliberately outside this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, TypeAdapter, field_validator, model_validator

from ecoguard.detectors.air_pollution.schemas import ContractModel
from ecoguard.analyzers.air_pollution.transport_schemas import (
    DirectionDegrees,
    NonNegativeFloat,
    SettlementTransportRelevanceResult,
    TransportCorridorMethod,
    TransportDataStatus,
)
from ecoguard.analyzers.air_pollution.settlement_ranking import SettlementSpatialRankingResult
from ecoguard.analyzers.air_pollution.transport_geometry import smallest_angular_difference_deg


CorridorHalfAngleDegrees = Annotated[float, Field(gt=0, lt=180, strict=True)]
PositiveDistanceMetres = Annotated[float, Field(gt=0, strict=True)]
RankingInput: TypeAlias = SettlementSpatialRankingResult | Mapping[str, object]


class TransportCorridorParameters(ContractModel):
    """Explicit policy inputs; direction variability never selects width here."""

    corridor_method: TransportCorridorMethod
    corridor_half_angle_deg: CorridorHalfAngleDegrees
    max_screening_distance_m: PositiveDistanceMetres
    direction_stddev_deg: NonNegativeFloat | None = None


class CorridorBoundaryBearings(ContractModel):
    """Normalized bearings for the two radial sides of the screening sector."""

    counterclockwise_boundary_bearing_deg: DirectionDegrees
    centerline_bearing_deg: DirectionDegrees
    clockwise_boundary_bearing_deg: DirectionDegrees


class TransportCorridorScreeningResult(ContractModel):
    """Available or unavailable corridor calculation, never an impact claim."""

    result_kind: Literal["potential_transport_screening_corridor"] = (
        "potential_transport_screening_corridor"
    )
    data_status: TransportDataStatus
    parameters: TransportCorridorParameters
    downwind_to_direction_deg: DirectionDegrees | None = None
    boundary_bearings: CorridorBoundaryBearings | None = None
    settlement_results: list[SettlementTransportRelevanceResult] = Field(
        default_factory=list
    )
    limitations: list[str] = Field(min_length=1)
    potential_downwind_relevance: Literal["indeterminate"] = "indeterminate"
    exposure_not_confirmed: Literal[True] = True

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, values: list[str]) -> list[str]:
        """Reject a blank limitation, since an empty caveat says nothing."""
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("limitations cannot contain blank entries")
        return stripped

    @model_validator(mode="after")
    def validate_availability(self):
        """Reject a result that is both unavailable and carrying a corridor."""
        has_any_geometry = (
            self.downwind_to_direction_deg is not None
            or self.boundary_bearings is not None
        )
        has_complete_geometry = (
            self.downwind_to_direction_deg is not None
            and self.boundary_bearings is not None
        )
        if self.data_status == "unavailable":
            if has_any_geometry or self.settlement_results:
                raise ValueError(
                    "unavailable corridor cannot contain geometry or settlement results"
                )
        elif not has_complete_geometry:
            raise ValueError("available corridor requires direction and boundary bearings")
        return self


class _BoundaryBearingInput(ContractModel):
    downwind_to_direction_deg: DirectionDegrees
    corridor_half_angle_deg: CorridorHalfAngleDegrees


def corridor_boundary_bearings(
    downwind_to_direction_deg: float,
    corridor_half_angle_deg: float,
) -> CorridorBoundaryBearings:
    """Return normalized counterclockwise, center, and clockwise bearings."""

    values = _BoundaryBearingInput(
        downwind_to_direction_deg=downwind_to_direction_deg,
        corridor_half_angle_deg=corridor_half_angle_deg,
    )
    return CorridorBoundaryBearings(
        counterclockwise_boundary_bearing_deg=(
            values.downwind_to_direction_deg - values.corridor_half_angle_deg
        )
        % 360.0,
        centerline_bearing_deg=values.downwind_to_direction_deg,
        clockwise_boundary_bearing_deg=(
            values.downwind_to_direction_deg + values.corridor_half_angle_deg
        )
        % 360.0,
    )


def _validated_ranking(value: RankingInput) -> SettlementSpatialRankingResult:
    """One ranking result, rejecting anything malformed."""
    payload = (
        value.model_dump()
        if isinstance(value, SettlementSpatialRankingResult)
        else value
    )
    return SettlementSpatialRankingResult.model_validate(payload)


def _exclusion_reason(
    settlement: SettlementSpatialRankingResult,
    parameters: TransportCorridorParameters,
) -> Literal[
    "outside_transport_corridor",
    "upwind_of_origin",
    "beyond_screening_range",
] | None:
    """Return one transparent reason using a documented precedence order."""

    if settlement.along_wind_distance_m < 0.0:
        return "upwind_of_origin"
    if settlement.geodesic_distance_m > parameters.max_screening_distance_m:
        return "beyond_screening_range"
    if (
        settlement.along_wind_distance_m == 0.0
        or settlement.angular_difference_deg > parameters.corridor_half_angle_deg
    ):
        return "outside_transport_corridor"
    return None


def apply_transport_corridor(
    ranked_settlements: Sequence[RankingInput],
    *,
    downwind_to_direction_deg: float,
    corridor_half_angle_deg: float,
    max_screening_distance_m: float,
    corridor_method: TransportCorridorMethod,
    direction_stddev_deg: float | None = None,
    data_status: Literal["success", "partial"] = "success",
) -> TransportCorridorScreeningResult:
    """Apply inclusive angle/distance boundaries to EA-319 ranking results.

    Membership requires a strictly positive along-wind component, angular
    difference less than or equal to the half-angle, and distance less than or
    equal to the maximum. Directional consistency with the supplied centerline
    is checked using the EA-318 angular helper.
    """

    parameters = TransportCorridorParameters(
        corridor_method=corridor_method,
        corridor_half_angle_deg=corridor_half_angle_deg,
        max_screening_distance_m=max_screening_distance_m,
        direction_stddev_deg=direction_stddev_deg,
    )
    direction = TypeAdapter(DirectionDegrees).validate_python(
        downwind_to_direction_deg
    )
    settlements = [_validated_ranking(item) for item in ranked_settlements]
    identifiers = [item.settlement_id for item in settlements]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("settlement IDs must be unique")

    ranks = [item.rank for item in settlements]
    if len(set(ranks)) != len(ranks):
        raise ValueError("settlement ranks must be unique")

    results: list[SettlementTransportRelevanceResult] = []
    for settlement in settlements:
        expected_difference = smallest_angular_difference_deg(
            settlement.bearing_from_origin_deg,
            direction,
        )
        if abs(expected_difference - settlement.angular_difference_deg) > 1e-9:
            raise ValueError(
                f"settlement {settlement.settlement_id!r} angular difference "
                "does not match the corridor centerline"
            )

        exclusion_reason = _exclusion_reason(settlement, parameters)
        inside = exclusion_reason is None
        results.append(
            SettlementTransportRelevanceResult(
                settlement_id=settlement.settlement_id,
                name=settlement.name,
                coordinates=settlement.coordinates,
                geodesic_distance_m=settlement.geodesic_distance_m,
                bearing_from_origin_deg=settlement.bearing_from_origin_deg,
                angular_difference_deg=settlement.angular_difference_deg,
                along_wind_distance_m=settlement.along_wind_distance_m,
                crosswind_distance_m=settlement.crosswind_distance_m,
                inside_transport_corridor=inside,
                relevance_score=settlement.relevance_score,
                score_components=settlement.score_components.model_dump(),
                rank=settlement.rank if inside else None,
                exclusion_reason=exclusion_reason,
                potential_downwind_relevance=(
                    "indeterminate" if inside else "outside_screening_corridor"
                ),
            )
        )

    return TransportCorridorScreeningResult(
        data_status=data_status,
        parameters=parameters,
        downwind_to_direction_deg=direction,
        boundary_bearings=corridor_boundary_bearings(
            direction,
            parameters.corridor_half_angle_deg,
        ),
        settlement_results=results,
        limitations=[
            "Geometric screening corridor only; transport and exposure are not confirmed."
        ],
    )


def unavailable_transport_corridor(
    *,
    corridor_half_angle_deg: float,
    max_screening_distance_m: float,
    corridor_method: TransportCorridorMethod,
    limitation: str,
    direction_stddev_deg: float | None = None,
) -> TransportCorridorScreeningResult:
    """Represent absence of a defensible direction without fabricating geometry."""

    return TransportCorridorScreeningResult(
        data_status="unavailable",
        parameters=TransportCorridorParameters(
            corridor_method=corridor_method,
            corridor_half_angle_deg=corridor_half_angle_deg,
            max_screening_distance_m=max_screening_distance_m,
            direction_stddev_deg=direction_stddev_deg,
        ),
        limitations=[limitation],
    )
