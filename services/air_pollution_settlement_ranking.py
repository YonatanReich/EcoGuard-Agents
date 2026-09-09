"""Deterministic settlement ranking for pollution transport screening.

The ranking describes geometry relative to an analysis origin and normalized
wind evidence. It does not establish a pollution source, transport, exposure,
impact, arrival, concentration, or probability.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import cos, isclose, radians, sin
from typing import Literal, TypeAlias

from pydantic import Field

from agents.air_pollution_anomaly_schemas import ContractModel, GeographicCoordinate
from agents.air_pollution_transport_schemas import (
    AngularDifferenceDegrees,
    DirectionDegrees,
    NonNegativeFloat,
    PositiveRank,
    RelevanceScore,
    SettlementTransportCandidate,
    SignedFloat,
)
from services.air_pollution_transport_geometry import (
    CoordinateInput,
    UndefinedBearingError,
    downwind_to_direction_deg,
    geodesic_distance_m,
    initial_bearing_deg,
    smallest_angular_difference_deg,
)


CandidateInput: TypeAlias = SettlementTransportCandidate | Mapping[str, object]
RANKING_ALGORITHM_VERSION = "direction-first-v1"
SCORE_METHOD = "positive_directional_alignment_cosine"


class ZeroDistanceSettlementError(UndefinedBearingError):
    """Raised when a settlement at the origin has no directional geometry."""


class DirectionalAlignmentScoreComponents(ContractModel):
    """Visible component of a heuristic geometric score, never probability."""

    directional_alignment: RelevanceScore


class SettlementSpatialRankingResult(ContractModel):
    """EA-319 intermediate result; corridor fields are intentionally absent."""

    settlement_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    coordinates: GeographicCoordinate
    geodesic_distance_m: NonNegativeFloat
    bearing_from_origin_deg: DirectionDegrees
    angular_difference_deg: AngularDifferenceDegrees
    along_wind_distance_m: SignedFloat
    crosswind_distance_m: NonNegativeFloat
    relevance_score: RelevanceScore
    ranking_algorithm_version: Literal["direction-first-v1"] = (
        RANKING_ALGORITHM_VERSION
    )
    score_kind: Literal["heuristic_geometric_relevance"] = (
        "heuristic_geometric_relevance"
    )
    score_method: Literal["positive_directional_alignment_cosine"] = SCORE_METHOD
    score_components: DirectionalAlignmentScoreComponents
    rank: PositiveRank
    potential_downwind_relevance: Literal["indeterminate"] = "indeterminate"
    exposure_not_confirmed: Literal[True] = True


def _validated_candidate(value: CandidateInput) -> SettlementTransportCandidate:
    payload = (
        value.model_dump()
        if isinstance(value, SettlementTransportCandidate)
        else value
    )
    return SettlementTransportCandidate.model_validate(payload)


def _snap_trigonometric_zero(value: float) -> float:
    return 0.0 if isclose(value, 0.0, abs_tol=1e-15) else value


def rank_settlement_candidates(
    analysis_origin_coordinates: CoordinateInput,
    wind_from_direction_deg: float,
    settlement_candidates: Sequence[CandidateInput],
) -> list[SettlementSpatialRankingResult]:
    """Calculate and rank settlement geometry relative to downwind direction.

    Ordering is deterministic and ascending by:

    1. positive along-wind component before perpendicular/upwind components;
    2. angular difference from downwind direction;
    3. great-circle distance;
    4. stable settlement ID using Python's deterministic string ordering.

    The score is only ``max(0, cos(angular_difference))``. Distance influences
    tie-breaking, but is deliberately absent from the score. A coincident
    settlement raises :class:`ZeroDistanceSettlementError` rather than being
    assigned a fabricated bearing or directional alignment.
    """

    origin_payload = (
        analysis_origin_coordinates.model_dump()
        if isinstance(analysis_origin_coordinates, GeographicCoordinate)
        else analysis_origin_coordinates
    )
    origin = GeographicCoordinate.model_validate(origin_payload)
    downwind_direction = downwind_to_direction_deg(wind_from_direction_deg)
    candidates = [_validated_candidate(item) for item in settlement_candidates]
    identifiers = [item.settlement_id for item in candidates]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("settlement candidate IDs must be unique")

    calculated: list[dict[str, object]] = []
    for candidate in candidates:
        distance_m = geodesic_distance_m(
            origin,
            candidate.coordinates,
        )
        if distance_m == 0.0:
            raise ZeroDistanceSettlementError(
                f"settlement {candidate.settlement_id!r} is at the analysis origin; "
                "directional ranking is undefined"
            )

        bearing = initial_bearing_deg(
            origin,
            candidate.coordinates,
        )
        angular_difference = smallest_angular_difference_deg(
            bearing,
            downwind_direction,
        )
        angular_difference_radians = radians(angular_difference)
        cosine = _snap_trigonometric_zero(cos(angular_difference_radians))
        sine = _snap_trigonometric_zero(sin(angular_difference_radians))
        along_wind_distance_m = distance_m * cosine
        crosswind_distance_m = abs(distance_m * sine)
        directional_alignment = max(0.0, cosine)

        calculated.append(
            {
                "settlement_id": candidate.settlement_id,
                "name": candidate.name,
                "coordinates": candidate.coordinates,
                "geodesic_distance_m": distance_m,
                "bearing_from_origin_deg": bearing,
                "angular_difference_deg": angular_difference,
                "along_wind_distance_m": along_wind_distance_m,
                "crosswind_distance_m": crosswind_distance_m,
                "relevance_score": directional_alignment,
                "score_components": {
                    "directional_alignment": directional_alignment,
                },
            }
        )

    calculated.sort(
        key=lambda item: (
            0 if item["along_wind_distance_m"] > 0.0 else 1,
            item["angular_difference_deg"],
            item["geodesic_distance_m"],
            item["settlement_id"],
        )
    )
    return [
        SettlementSpatialRankingResult(rank=rank, **item)
        for rank, item in enumerate(calculated, start=1)
    ]
