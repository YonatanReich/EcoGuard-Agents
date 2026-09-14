"""Bounded shared-observation to Air Pollution detector connection.

This module owns no schedule, cursor, persistence, retry loop, candidate store,
or downstream routing. It reads a caller-selected batch, strips the collection
envelope explicitly, performs the active baseline lookup, and returns one
detector result for every input row in the same order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, Field, ValidationError

from agents.air_pollution_anomaly_detector import AirPollutionAnomalyDetector
from agents.air_pollution_anomaly_schemas import (
    AnomalyContract,
    AirPollutionDetectionResult,
)
from services.air_pollution_baseline_schemas import LiveBaselineContextResult
from services.air_pollution_live_baseline import (
    LIVE_BASELINE_FAMILY,
    AirPollutionLiveBaselineContextService,
)
from services.air_quality_schemas import AirQualityObservation

AIR_POLLUTION_SOURCE = "air_pollution"

# Deliberately excludes collector envelope fields such as collected_at and
# collection_status. New envelope metadata cannot silently enter the strict
# provider-observation contract merely because it was added to JSONB.
AIR_QUALITY_PAYLOAD_FIELDS = frozenset(AirQualityObservation.model_fields)

ObservationReader = Callable[..., list[dict[str, Any]]]


def _default_reader(**kwargs):
    from ecoguard.database.repositories.observations import read_observations_batch

    return read_observations_batch(**kwargs)


class PersistedObservationAdapterError(ValueError):
    """Sanitized reason why a shared row cannot become a provider observation."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def air_quality_observation_from_row(
    row: Mapping[str, Any],
) -> AirQualityObservation:
    """Hydrate one strict observation without passing through envelope fields."""

    if row.get("source") != AIR_POLLUTION_SOURCE:
        raise PersistedObservationAdapterError("unexpected_observation_source")
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        raise PersistedObservationAdapterError("malformed_observation_payload")
    observed_at = row.get("observed_at")
    if not isinstance(observed_at, datetime):
        raise PersistedObservationAdapterError("missing_observed_at")

    values = {
        field: payload[field]
        for field in AIR_QUALITY_PAYLOAD_FIELDS
        if field in payload and field != "observed_at"
    }
    values["observed_at"] = observed_at

    latitude, longitude = row.get("latitude"), row.get("longitude")
    if (latitude is None) != (longitude is None):
        raise PersistedObservationAdapterError("incomplete_observation_location")
    if latitude is not None:
        values["location"] = {"latitude": latitude, "longitude": longitude}

    try:
        return AirQualityObservation.model_validate(values)
    except (ValidationError, TypeError, ValueError):
        raise PersistedObservationAdapterError(
            "invalid_air_quality_observation"
        ) from None


class PersistedAirPollutionDetection(AnomalyContract):
    """Auditable ordered result for one shared observation row."""

    observation_id: int | None = Field(default=None, ge=1)
    source: str | None = None
    cell_id: str | None = None
    ingested_at: AwareDatetime | None = None
    baseline_family: Literal["five_minute_observation"] = LIVE_BASELINE_FAMILY
    live_observation: AirQualityObservation | None = None
    baseline_context: LiveBaselineContextResult
    detection: AirPollutionDetectionResult
    live_value: float | None = None
    baseline_p95: float | None = None
    detector_status: Literal["NORMAL", "SUSPECTED_ANOMALY", "NOT_EVALUATED"]
    detector_reason: str


class AirPollutionObservationProcessor:
    """Read or accept a bounded row batch and run the operational detector path."""

    def __init__(
        self,
        *,
        reader: ObservationReader = _default_reader,
        baseline_context_service: AirPollutionLiveBaselineContextService | None = None,
        detector: AirPollutionAnomalyDetector | None = None,
    ) -> None:
        self.reader = reader
        self.baseline_context_service = (
            baseline_context_service or AirPollutionLiveBaselineContextService()
        )
        self.detector = detector or AirPollutionAnomalyDetector()

    def read_and_process(
        self,
        *,
        ingested_after: datetime | None = None,
        after_id: int | None = None,
        ingested_through: datetime | None = None,
        limit: int = 500,
    ) -> list[PersistedAirPollutionDetection]:
        rows = self.reader(
            source=AIR_POLLUTION_SOURCE,
            ingested_after=ingested_after,
            after_id=after_id,
            ingested_through=ingested_through,
            limit=limit,
        )
        return self.process_rows(rows)

    def process_rows(
        self, rows: Iterable[Mapping[str, Any]],
    ) -> list[PersistedAirPollutionDetection]:
        supplied = list(rows)
        contexts: list[LiveBaselineContextResult | None] = [None] * len(supplied)
        observations: list[AirQualityObservation | None] = [None] * len(supplied)
        valid_indexes: list[int] = []
        valid_observations: list[AirQualityObservation] = []

        for index, row in enumerate(supplied):
            try:
                observation = air_quality_observation_from_row(row)
            except PersistedObservationAdapterError as error:
                contexts[index] = LiveBaselineContextResult(
                    status="invalid_live_observation",
                    reason=error.reason,
                    mode="operational",
                    comparison_eligible=False,
                    eligibility_reason=error.reason,
                )
                continue
            observations[index] = observation
            valid_indexes.append(index)
            valid_observations.append(observation)

        if valid_observations:
            resolved = self.baseline_context_service.lookup_batch(valid_observations)
            if len(resolved) != len(valid_indexes):
                raise RuntimeError("baseline context batch did not preserve every input")
            for index, context in zip(valid_indexes, resolved, strict=True):
                contexts[index] = context

        output: list[PersistedAirPollutionDetection] = []
        for row, observation, context in zip(
            supplied, observations, contexts, strict=True
        ):
            if context is None:
                raise RuntimeError("processor did not preserve every input")
            detection = self.detector.detect(context)
            statistics = context.baseline_statistics
            output.append(PersistedAirPollutionDetection(
                observation_id=(
                    row.get("id") if type(row.get("id")) is int and row.get("id") > 0
                    else None
                ),
                source=str(row["source"]) if row.get("source") is not None else None,
                cell_id=str(row["cell_id"]) if row.get("cell_id") is not None else None,
                ingested_at=(
                    row.get("ingested_at")
                    if isinstance(row.get("ingested_at"), datetime)
                    else None
                ),
                live_observation=observation,
                baseline_context=context,
                detection=detection,
                live_value=observation.value if observation is not None else None,
                baseline_p95=statistics.p95 if statistics is not None else None,
                detector_status=detection.status,
                detector_reason=detection.reason,
            ))
        return output
