"""Transitional orchestration for provider-backed pollution transport screening.

The service is independent of FastAPI, scheduling, and persistence so it can
move behind the future generic Coordinator unchanged. It composes the existing
EA-318 through EA-322 calculations and never invokes response planning.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field

from agents.air_pollution_anomaly_schemas import ContractModel, GeographicCoordinate
from agents.air_pollution_correlation import PollutionCorrelationCandidate
from agents.air_pollution_transport_schemas import (
    AnalysisOrigin,
    SettlementTransportCandidate,
    WindEvidence,
)
from services.air_pollution_settlement_ranking import rank_settlement_candidates
from services.air_pollution_transport_corridor import (
    TransportCorridorScreeningResult,
    apply_transport_corridor,
)
from services.air_pollution_transport_geometry import downwind_to_direction_deg
from services.air_pollution_transport_spatial_output import (
    PollutionTransportSpatialOutput,
    prepare_transport_spatial_output,
)
from services.air_pollution_transport_time import (
    apply_transport_time_estimate,
    estimate_corridor_settlement_transport_time,
)
from services.ims_wind_evidence_service import IMSWindEvidenceService
from services.ims_wind_observation_client import IMSWindObservationClient


TRANSPORT_ENABLED_ENV = "AIR_POLLUTION_TRANSPORT_SCREENING_ENABLED"
TRANSPORT_HALF_ANGLE_ENV = "AIR_POLLUTION_TRANSPORT_HALF_ANGLE_DEG"
TRANSPORT_MAX_DISTANCE_ENV = "AIR_POLLUTION_TRANSPORT_MAX_DISTANCE_M"
TRANSPORT_ARC_SEGMENTS_ENV = "AIR_POLLUTION_TRANSPORT_ARC_SEGMENT_COUNT"
WIND_MAX_AGE_MINUTES_ENV = "AIR_POLLUTION_WIND_MAX_AGE_MINUTES"
TRANSPORT_MIN_WIND_SPEED_ENV = "AIR_POLLUTION_TRANSPORT_MIN_WIND_SPEED_MPS"


class AirPollutionTransportConfigurationError(RuntimeError):
    """A safe configuration failure that contains no environment values."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


class AirPollutionTransportConfiguration(ContractModel):
    corridor_method: Literal["fixed_angle_screening"] = "fixed_angle_screening"
    corridor_half_angle_deg: float = Field(gt=0, lt=180, strict=True)
    max_screening_distance_m: float = Field(gt=0, strict=True)
    arc_segment_count: int = Field(ge=1, strict=True)
    wind_max_age_minutes: float = Field(gt=0, strict=True)
    minimum_wind_speed_mps: float | None = Field(default=None, gt=0, strict=True)


class WindEvidenceProvider(Protocol):
    def select_wind_evidence(
        self,
        *,
        analysis_coordinates: GeographicCoordinate,
        anomaly_observed_at: datetime,
        maximum_observation_age_seconds: float,
        alternative_limit: int = 3,
    ): ...


class AirPollutionTransportPredictionExecution(ContractModel):
    analysis_origin: AnalysisOrigin
    wind_evidence: WindEvidence
    spatial_output: PollutionTransportSpatialOutput
    exposure_not_confirmed: Literal[True] = True


def _enabled_from_environment() -> bool:
    raw = os.getenv(TRANSPORT_ENABLED_ENV)
    if raw is None or not raw.strip():
        return False
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AirPollutionTransportConfigurationError(
        "air_pollution_transport_enabled_value_invalid"
    )


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise AirPollutionTransportConfigurationError(
            "air_pollution_transport_required_configuration_missing"
        )
    return value.strip()


def _finite_float(name: str, *, required: bool) -> float | None:
    raw = _required_environment(name) if required else os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        raise AirPollutionTransportConfigurationError(
            "air_pollution_transport_configuration_invalid"
        ) from None
    if not math.isfinite(value):
        raise AirPollutionTransportConfigurationError(
            "air_pollution_transport_configuration_invalid"
        )
    return value


def load_air_pollution_transport_configuration(
) -> AirPollutionTransportConfiguration | None:
    """Load explicit screening policy; absence of the enable flag disables it."""

    if not _enabled_from_environment():
        return None
    try:
        arc_segments = int(_required_environment(TRANSPORT_ARC_SEGMENTS_ENV))
        return AirPollutionTransportConfiguration(
            corridor_half_angle_deg=_finite_float(
                TRANSPORT_HALF_ANGLE_ENV, required=True
            ),
            max_screening_distance_m=_finite_float(
                TRANSPORT_MAX_DISTANCE_ENV, required=True
            ),
            arc_segment_count=arc_segments,
            wind_max_age_minutes=_finite_float(
                WIND_MAX_AGE_MINUTES_ENV, required=True
            ),
            minimum_wind_speed_mps=_finite_float(
                TRANSPORT_MIN_WIND_SPEED_ENV, required=False
            ),
        )
    except AirPollutionTransportConfigurationError:
        raise
    except (TypeError, ValueError):
        raise AirPollutionTransportConfigurationError(
            "air_pollution_transport_configuration_invalid"
        ) from None


def _settlement_id(
    source: str | None,
    feature,
) -> tuple[str, str | None]:
    if feature.osm_id is not None and feature.osm_type is not None:
        identifier = f"osm:{feature.osm_type}:{feature.osm_id}"
        return identifier, f"{feature.osm_type}:{feature.osm_id}"
    if feature.ref:
        prefix = source or "spatial-context"
        return f"{prefix}:ref:{feature.ref}", feature.ref
    assert feature.name is not None
    return (
        f"coordinate:{feature.latitude:.7f}:{feature.longitude:.7f}:{feature.name}",
        None,
    )


def settlement_candidates_from_spatial_context(
    candidate: PollutionCorrelationCandidate,
) -> list[SettlementTransportCandidate]:
    """Map only real EA-310 settlement points; missing fields are not fabricated."""

    context = candidate.spatial_context
    if context is None or context.status == "unavailable":
        return []
    settlements: list[SettlementTransportCandidate] = []
    seen: set[str] = set()
    for feature in context.nearby_settlements:
        if (
            feature.name is None
            or feature.latitude is None
            or feature.longitude is None
        ):
            continue
        settlement_id, source_feature_id = _settlement_id(context.source, feature)
        if settlement_id in seen:
            continue
        seen.add(settlement_id)
        settlements.append(
            SettlementTransportCandidate(
                settlement_id=settlement_id,
                name=feature.name,
                coordinates=GeographicCoordinate(
                    latitude=feature.latitude,
                    longitude=feature.longitude,
                ),
                source_provider=context.source,
                source_feature_id=source_feature_id,
                original_source_distance_m=(
                    feature.distance_km * 1000.0
                    if feature.distance_km is not None
                    else None
                ),
            )
        )
    return settlements


class AirPollutionTransportPredictionService:
    """Compose real wind evidence and existing deterministic screening modules."""

    def __init__(
        self,
        *,
        wind_evidence_service: WindEvidenceProvider,
        configuration: AirPollutionTransportConfiguration,
    ) -> None:
        self.wind_evidence_service = wind_evidence_service
        self.configuration = AirPollutionTransportConfiguration.model_validate(
            configuration.model_dump()
        )

    def obtain_wind_evidence(
        self,
        candidate: PollutionCorrelationCandidate,
    ) -> WindEvidence:
        validated = PollutionCorrelationCandidate.model_validate(
            candidate.model_dump(round_trip=True)
        )
        selection = self.wind_evidence_service.select_wind_evidence(
            analysis_coordinates=validated.anomaly.location,
            anomaly_observed_at=validated.anomaly.observed_at,
            maximum_observation_age_seconds=(
                self.configuration.wind_max_age_minutes * 60.0
            ),
        )
        return WindEvidence.model_validate(
            selection.wind_evidence.model_dump(round_trip=True)
        )

    def predict(
        self,
        candidate: PollutionCorrelationCandidate,
        *,
        wind_evidence: WindEvidence | Mapping[str, object] | None = None,
    ) -> AirPollutionTransportPredictionExecution:
        validated = PollutionCorrelationCandidate.model_validate(
            candidate.model_dump(round_trip=True)
        )
        evidence = (
            self.obtain_wind_evidence(validated)
            if wind_evidence is None
            else WindEvidence.model_validate(
                wind_evidence.model_dump(round_trip=True)
                if isinstance(wind_evidence, WindEvidence)
                else wind_evidence
            )
        )
        if evidence.requested_coordinates != validated.anomaly.location:
            raise ValueError("wind evidence coordinates do not match analysis origin")
        expected_offset = (
            evidence.effective_at - validated.anomaly.observed_at
        ).total_seconds()
        if abs(expected_offset - evidence.time_offset_from_anomaly_seconds) > 1e-6:
            raise ValueError("wind evidence time offset does not match anomaly")

        settlements = settlement_candidates_from_spatial_context(validated)
        rankings = rank_settlement_candidates(
            validated.anomaly.location,
            evidence.wind_from_direction_deg,
            settlements,
        )
        downwind_direction = downwind_to_direction_deg(
            evidence.wind_from_direction_deg
        )
        corridor = apply_transport_corridor(
            rankings,
            downwind_to_direction_deg=downwind_direction,
            corridor_half_angle_deg=self.configuration.corridor_half_angle_deg,
            max_screening_distance_m=self.configuration.max_screening_distance_m,
            corridor_method=self.configuration.corridor_method,
            direction_stddev_deg=evidence.direction_stddev_deg,
        )
        timed_settlements = []
        for settlement in corridor.settlement_results:
            estimate = estimate_corridor_settlement_transport_time(
                settlement,
                evidence,
                wind_evidence_suitability="usable",
                minimum_wind_speed_mps=self.configuration.minimum_wind_speed_mps,
            )
            timed_settlements.append(
                apply_transport_time_estimate(settlement, estimate)
            )
        corridor_payload = corridor.model_dump()
        corridor_payload["settlement_results"] = [
            settlement.model_dump() for settlement in timed_settlements
        ]
        corridor_payload["limitations"] = [
            *corridor.limitations,
            "Analysis origin is a monitoring location, not a confirmed emission source.",
            "Downwind screening is relative to the monitoring location; exposure is not confirmed.",
        ]
        corridor_with_time = TransportCorridorScreeningResult.model_validate(
            corridor_payload
        )
        spatial_output = prepare_transport_spatial_output(
            validated.anomaly.location,
            corridor_with_time,
            arc_segment_count=self.configuration.arc_segment_count,
        )
        return AirPollutionTransportPredictionExecution(
            analysis_origin=AnalysisOrigin(
                analysis_origin_kind="monitoring_location",
                analysis_origin_coordinates=validated.anomaly.location,
            ),
            wind_evidence=evidence,
            spatial_output=spatial_output,
        )


def configured_air_pollution_transport_prediction_service(
) -> AirPollutionTransportPredictionService | None:
    """Build the IMS-backed bridge only when explicitly enabled and configured."""

    configuration = load_air_pollution_transport_configuration()
    if configuration is None:
        return None
    return AirPollutionTransportPredictionService(
        wind_evidence_service=IMSWindEvidenceService(
            IMSWindObservationClient()
        ),
        configuration=configuration,
    )
