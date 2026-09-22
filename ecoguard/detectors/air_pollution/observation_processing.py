"""Bounded shared-observation to Air Pollution detector connection.

This module owns no schedule, candidate store, or downstream routing. It reads
a caller-selected batch, strips the collection envelope explicitly, performs
the active baseline lookup, and returns one detector result for every input row
in the same order. ``detect_new`` is the scheduled detector entry point: it
uses the shared ``collector_runs`` bookmark and leaves scheduling and
coordination to the shared runtime.
"""

from __future__ import annotations

from ecoguard.shared.activity import live_actor

import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, Field, ValidationError

from ecoguard.detectors.air_pollution.detector import AirPollutionAnomalyDetector
from ecoguard.detectors.air_pollution.cell_signal_adapter import (
    AirPollutionCellSignalAdapterError,
    air_pollution_detection_to_cell_signal,
)
from ecoguard.detectors.air_pollution.correlation import correlation_candidate
from ecoguard.detectors.air_pollution.spatial_enrichment import (
    AirPollutionSpatialEnricher,
)
from ecoguard.detectors.air_pollution.schemas import (
    AnomalyContract,
    AirPollutionDetectionResult,
)
from ecoguard.detectors.air_pollution.baseline_schemas import LiveBaselineContextResult
from ecoguard.detectors.air_pollution.live_baseline import (
    LIVE_BASELINE_FAMILY,
    AirPollutionLiveBaselineContextService,
)
from ecoguard.shared.air_quality_schemas import AirQualityObservation
from ecoguard.shared.signals import CellSignal

logger = logging.getLogger(__name__)

AIR_POLLUTION_SOURCE = "air_pollution"
RUN_SOURCE = "detector_air_pollution"
DETECTION_BATCH_SIZE = 500

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


@live_actor("detector.air_pollution")
def detect_new(
    *,
    processor: AirPollutionObservationProcessor | None = None,
    spatial_enricher: AirPollutionSpatialEnricher | None = None,
    spatial_radius_km: float | None = None,
    at: datetime | None = None,
) -> list[CellSignal]:
    """Convert newly ingested persisted observations to qualified signals.

    The durable bookmark is this detector's last successful ``collector_runs``
    start time. The current run is logged before reading, so rows arriving
    during the sweep overlap the next run rather than falling into a gap. A
    fixed upper bound makes pagination deterministic, and ``after_id`` safely
    advances through collector batches that share one ingestion timestamp.

    NORMAL, NOT_EVALUATED, and safely rejected candidates advance the bookmark
    but emit nothing. Unexpected processing failures mark the run failed and
    leave the previous successful bookmark in force for a retry.
    """
    from ecoguard.database.repositories.collector_runs import (
        last_success_at,
        log_finish,
        log_start,
    )

    since = last_success_at(RUN_SOURCE)
    run_id = log_start(RUN_SOURCE)
    try:
        through = at or datetime.now(timezone.utc)
        if through.tzinfo is None or through.utcoffset() is None:
            raise ValueError("at must carry a UTC offset")
        through = through.astimezone(timezone.utc)
        cursor_at = since
        cursor_id = 0 if since is not None else None
        service = processor or AirPollutionObservationProcessor()
        # Production spatial enrichment belongs after event qualification and
        # publication gating.  Explicit injection remains available for
        # focused callers and tests, but detection itself performs no town
        # lookup merely because transport screening is configured.
        enrichment = spatial_enricher
        enrichment_radius = spatial_radius_km
        if (enrichment is None) != (enrichment_radius is None):
            raise ValueError(
                "spatial_enricher and spatial_radius_km must be supplied together"
            )
        signals: list[CellSignal] = []
        examined = 0

        while True:
            results = service.read_and_process(
                ingested_after=cursor_at,
                after_id=cursor_id,
                ingested_through=through,
                limit=DETECTION_BATCH_SIZE,
            )
            if not results:
                break

            examined += len(results)
            for result in results:
                if result.detector_status != "SUSPECTED_ANOMALY":
                    continue
                try:
                    candidate = None
                    if enrichment is not None and enrichment_radius is not None:
                        enriched = enrichment.enrich_detection_result(
                            result.detection,
                            radius_km=enrichment_radius,
                        )
                        if enriched is None:
                            raise RuntimeError(
                                "qualified anomaly was not spatially enriched"
                            )
                        candidate = correlation_candidate(enriched)
                    signals.append(
                        air_pollution_detection_to_cell_signal(
                            result.detection,
                            candidate=candidate,
                        )
                    )
                except AirPollutionCellSignalAdapterError as error:
                    logger.warning(
                        "air pollution observation %s rejected by signal adapter: %s",
                        result.observation_id,
                        error.reason,
                    )

            tail = results[-1]
            if tail.ingested_at is None or tail.observation_id is None:
                raise RuntimeError("persisted result missing ingestion cursor")
            if cursor_at is not None and (
                tail.ingested_at,
                tail.observation_id,
            ) <= (cursor_at, cursor_id or 0):
                raise RuntimeError("persisted ingestion cursor did not advance")
            cursor_at = tail.ingested_at
            cursor_id = tail.observation_id
            if len(results) < DETECTION_BATCH_SIZE:
                break

        log_finish(run_id, status="ok", rows_written=len(signals))
        logger.info(
            "air pollution: %s signals from %s persisted observations since %s",
            len(signals),
            examined,
            since or "the beginning of the persisted stream",
        )
        return signals
    except Exception as error:
        log_finish(
            run_id,
            status="failed",
            error=f"{type(error).__name__}: {error}",
        )
        raise
