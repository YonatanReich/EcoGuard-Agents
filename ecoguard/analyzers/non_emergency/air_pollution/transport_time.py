"""Nullable kinematic atmospheric transport-time screening estimates.

The duration is a constant-wind geometric screening value. It is not an ETA,
arrival prediction, exposure time, plume travel time, or operational response
time, and it carries no probability semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from ecoguard.detectors.air_pollution.schemas import ContractModel
from ecoguard.analyzers.non_emergency.air_pollution.transport_schemas import (
    NonNegativeFloat,
    SettlementTransportRelevanceResult,
    SignedFloat,
    TransportTimeMethod,
    WindEvidence,
)


WindEvidenceSuitability = Literal["usable", "insufficient"]
TransportTimeEstimateStatus = Literal["estimated", "suppressed"]
TransportTimeSuppressionReason = Literal[
    "zero_or_nonpositive_wind_speed",
    "zero_or_nonpositive_along_wind_distance",
    "insufficient_wind_evidence",
    "below_explicit_minimum_wind_speed",
    "settlement_not_downwind",
    "settlement_not_in_transport_corridor",
]
PositiveWindSpeed = Annotated[float, Field(gt=0, strict=True)]
SettlementResultInput: TypeAlias = (
    SettlementTransportRelevanceResult | Mapping[str, object]
)
WindEvidenceInput: TypeAlias = WindEvidence | Mapping[str, object]

TRANSPORT_TIME_ASSUMPTIONS: tuple[str, ...] = (
    "Wind speed is constant over the screening path.",
    "Wind direction is constant over the screening path.",
    "Surface wind is used as an atmospheric transport screening proxy.",
    "Atmospheric dispersion is not modeled.",
    "Plume rise is not modeled.",
    "Deposition and atmospheric chemistry are not modeled.",
    "Terrain and local-flow corrections are not modeled.",
    "The analysis origin may be a monitoring location rather than an emission source.",
)


class KinematicTransportTimeInput(ContractModel):
    """Validated scalar inputs for the provider-neutral core calculation."""

    along_wind_distance_m: SignedFloat
    wind_speed_mps: NonNegativeFloat
    wind_evidence_suitability: WindEvidenceSuitability
    minimum_wind_speed_mps: PositiveWindSpeed | None = None


class KinematicTransportTimeEstimate(ContractModel):
    """Duration or explicit suppression; never an absolute arrival claim."""

    estimate_status: TransportTimeEstimateStatus
    kinematic_advection_time_seconds: NonNegativeFloat | None = None
    transport_time_method: TransportTimeMethod | None = None
    transport_time_assumptions: list[str] = Field(min_length=1)
    suppression_reason: TransportTimeSuppressionReason | None = None
    along_wind_distance_m: SignedFloat
    wind_speed_mps: NonNegativeFloat
    minimum_wind_speed_mps: PositiveWindSpeed | None = None
    exposure_not_confirmed: Literal[True] = True

    @field_validator("transport_time_assumptions")
    @classmethod
    def validate_assumptions(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("transport-time assumptions cannot contain blank entries")
        return stripped

    @model_validator(mode="after")
    def validate_estimate_status(self):
        if self.estimate_status == "estimated":
            if (
                self.kinematic_advection_time_seconds is None
                or self.transport_time_method is None
                or self.suppression_reason is not None
            ):
                raise ValueError(
                    "estimated transport time requires duration and method only"
                )
        elif (
            self.kinematic_advection_time_seconds is not None
            or self.transport_time_method is not None
            or self.suppression_reason is None
        ):
            raise ValueError(
                "suppressed transport time requires only a suppression reason"
            )
        return self


def _result(
    inputs: KinematicTransportTimeInput,
    *,
    duration_seconds: float | None = None,
    suppression_reason: TransportTimeSuppressionReason | None = None,
) -> KinematicTransportTimeEstimate:
    estimated = duration_seconds is not None
    return KinematicTransportTimeEstimate(
        estimate_status="estimated" if estimated else "suppressed",
        kinematic_advection_time_seconds=duration_seconds,
        transport_time_method=(
            "constant_wind_kinematic_screening" if estimated else None
        ),
        transport_time_assumptions=list(TRANSPORT_TIME_ASSUMPTIONS),
        suppression_reason=suppression_reason,
        along_wind_distance_m=inputs.along_wind_distance_m,
        wind_speed_mps=inputs.wind_speed_mps,
        minimum_wind_speed_mps=inputs.minimum_wind_speed_mps,
    )


def estimate_kinematic_transport_time(
    along_wind_distance_m: float,
    wind_speed_mps: float,
    *,
    wind_evidence_suitability: WindEvidenceSuitability,
    minimum_wind_speed_mps: float | None = None,
) -> KinematicTransportTimeEstimate:
    """Return ``along_wind_distance_m / wind_speed_mps`` when eligible.

    No calm threshold is implicit. A caller may supply a strictly positive
    minimum wind speed; the exact threshold remains eligible and only speeds
    below it are suppressed.
    """

    inputs = KinematicTransportTimeInput(
        along_wind_distance_m=along_wind_distance_m,
        wind_speed_mps=wind_speed_mps,
        wind_evidence_suitability=wind_evidence_suitability,
        minimum_wind_speed_mps=minimum_wind_speed_mps,
    )
    if inputs.wind_evidence_suitability == "insufficient":
        return _result(inputs, suppression_reason="insufficient_wind_evidence")
    if inputs.along_wind_distance_m < 0.0:
        return _result(inputs, suppression_reason="settlement_not_downwind")
    if inputs.along_wind_distance_m == 0.0:
        return _result(
            inputs,
            suppression_reason="zero_or_nonpositive_along_wind_distance",
        )
    if inputs.wind_speed_mps == 0.0:
        return _result(
            inputs,
            suppression_reason="zero_or_nonpositive_wind_speed",
        )
    if (
        inputs.minimum_wind_speed_mps is not None
        and inputs.wind_speed_mps < inputs.minimum_wind_speed_mps
    ):
        return _result(
            inputs,
            suppression_reason="below_explicit_minimum_wind_speed",
        )

    duration_seconds = inputs.along_wind_distance_m / inputs.wind_speed_mps
    if not isfinite(duration_seconds):
        raise ValueError("kinematic transport duration must be finite")
    return _result(inputs, duration_seconds=duration_seconds)


def _validated_settlement(
    value: SettlementResultInput,
) -> SettlementTransportRelevanceResult:
    payload = (
        value.model_dump()
        if isinstance(value, SettlementTransportRelevanceResult)
        else value
    )
    return SettlementTransportRelevanceResult.model_validate(payload)


def _validated_wind_evidence(value: WindEvidenceInput) -> WindEvidence:
    payload = value.model_dump() if isinstance(value, WindEvidence) else value
    return WindEvidence.model_validate(payload)


def estimate_corridor_settlement_transport_time(
    settlement: SettlementResultInput,
    wind_evidence: WindEvidenceInput,
    *,
    wind_evidence_suitability: WindEvidenceSuitability,
    minimum_wind_speed_mps: float | None = None,
) -> KinematicTransportTimeEstimate:
    """Estimate time for a corridor-approved settlement using normalized wind.

    Full ``WindEvidence`` validation enforces source-specific observed/valid
    timestamp presence. Provider-invalid evidence is always insufficient;
    ``unknown`` evidence requires the caller's explicit suitability decision.
    Gust speed and original provider units are never used.
    """

    settlement_result = _validated_settlement(settlement)
    evidence = _validated_wind_evidence(wind_evidence)
    inputs = KinematicTransportTimeInput(
        along_wind_distance_m=settlement_result.along_wind_distance_m,
        wind_speed_mps=evidence.wind_speed_mps,
        wind_evidence_suitability=wind_evidence_suitability,
        minimum_wind_speed_mps=minimum_wind_speed_mps,
    )
    if settlement_result.along_wind_distance_m <= 0.0:
        reason: TransportTimeSuppressionReason = (
            "settlement_not_downwind"
            if settlement_result.along_wind_distance_m < 0.0
            else "zero_or_nonpositive_along_wind_distance"
        )
        return _result(inputs, suppression_reason=reason)
    if not settlement_result.inside_transport_corridor:
        return _result(
            inputs,
            suppression_reason="settlement_not_in_transport_corridor",
        )
    if evidence.provider_validity == "invalid":
        return _result(inputs, suppression_reason="insufficient_wind_evidence")
    return estimate_kinematic_transport_time(
        settlement_result.along_wind_distance_m,
        evidence.wind_speed_mps,
        wind_evidence_suitability=wind_evidence_suitability,
        minimum_wind_speed_mps=minimum_wind_speed_mps,
    )


def apply_transport_time_estimate(
    settlement: SettlementResultInput,
    estimate: KinematicTransportTimeEstimate | Mapping[str, object],
) -> SettlementTransportRelevanceResult:
    """Return an EA-317 settlement result carrying only an eligible estimate."""

    settlement_result = _validated_settlement(settlement)
    estimate_payload = (
        estimate.model_dump()
        if isinstance(estimate, KinematicTransportTimeEstimate)
        else estimate
    )
    validated_estimate = KinematicTransportTimeEstimate.model_validate(
        estimate_payload
    )
    if validated_estimate.estimate_status == "estimated":
        if (
            validated_estimate.along_wind_distance_m
            != settlement_result.along_wind_distance_m
        ):
            raise ValueError(
                "transport-time estimate does not match settlement geometry"
            )
        if not settlement_result.inside_transport_corridor:
            raise ValueError(
                "kinematic estimate cannot be attached to a corridor-excluded settlement"
            )
    payload = settlement_result.model_dump()
    if validated_estimate.estimate_status == "estimated":
        payload.update(
            kinematic_advection_time_seconds=(
                validated_estimate.kinematic_advection_time_seconds
            ),
            transport_time_method=validated_estimate.transport_time_method,
            transport_time_assumptions=(
                validated_estimate.transport_time_assumptions
            ),
        )
    else:
        payload.update(
            kinematic_advection_time_seconds=None,
            transport_time_method=None,
            transport_time_assumptions=[],
        )
    return SettlementTransportRelevanceResult.model_validate(payload)
