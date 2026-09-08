"""Replaceable runtime state boundary for the air-pollution pipeline.

The in-memory implementation is transitional.  Backend callers depend on the
protocol, so Yonatan's shared PostgreSQL/PostGIS repository can replace it
without changing the detector, downstream planner, API adapter, or frontend
contract.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field

from agents.air_pollution_anomaly_schemas import ContractModel
from agents.air_pollution_correlation import (
    PollutionCorrelationCandidate,
    PollutionCorrelationResult,
)
from agents.air_pollution_response_schemas import AirPollutionResponsePlan
from services.air_quality_schemas import AirQualityObservation


RuntimeStatus = Literal["not_started", "success", "partial", "failed"]


class StoredAirPollutionEvent(ContractModel):
    """Correlation-ready candidate plus optional downstream planning output.

    The event remains an anomaly candidate, not a final incident. The generic
    Coordinator/Strainer and its routing stage may later attach the plan after
    selecting the appropriate planner.
    """

    event: PollutionCorrelationCandidate
    correlation_evidence: PollutionCorrelationResult | None = None
    plan: AirPollutionResponsePlan | None = None


class AirPollutionRuntimeSnapshot(ContractModel):
    status: RuntimeStatus = "not_started"
    events: list[StoredAirPollutionEvent] = Field(default_factory=list)
    last_attempted_at: AwareDatetime | None = None
    last_successful_collection_at: AwareDatetime | None = None
    stale: bool = False
    observation_count: int = Field(default=0, ge=0)
    excluded_count: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)


class AirPollutionEventStore(Protocol):
    """Persistence seam required by collection, processing, and API reads."""

    def snapshot(self) -> AirPollutionRuntimeSnapshot: ...

    def append_observations(self, observations: list[AirQualityObservation]) -> None: ...

    def observation_series(self, observation: AirQualityObservation) -> list[AirQualityObservation]: ...

    def replace_events(
        self,
        events: list[StoredAirPollutionEvent],
        *,
        status: Literal["success", "partial"],
        attempted_at: datetime,
        collected_at: datetime,
        observation_count: int,
        excluded_count: int,
        errors: list[str],
    ) -> None: ...

    def record_failure(self, *, attempted_at: datetime, errors: list[str]) -> None: ...


def _copy_snapshot(value: AirPollutionRuntimeSnapshot) -> AirPollutionRuntimeSnapshot:
    return AirPollutionRuntimeSnapshot.model_validate(value.model_dump(round_trip=True))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("runtime timestamps must include a UTC offset")
    return value.astimezone(timezone.utc)


class InMemoryAirPollutionEventStore:
    """Bounded, process-local bridge until the shared database is available.

    It deliberately makes no durable-storage guarantees.  A provider failure
    retains the prior event snapshot but marks it stale; a successful refresh
    atomically replaces the current events, including with an empty list.
    """

    def __init__(self, *, history_hours: int = 48, max_samples_per_series: int = 600):
        if history_hours < 1 or max_samples_per_series < 1:
            raise ValueError("history bounds must be positive")
        self.history_hours = history_hours
        self.max_samples_per_series = max_samples_per_series
        self._lock = threading.RLock()
        self._snapshot = AirPollutionRuntimeSnapshot()
        self._history: dict[tuple[str, str, str, str, str], list[AirQualityObservation]] = {}

    @staticmethod
    def _series_key(item: AirQualityObservation) -> tuple[str, str, str, str, str]:
        return (
            item.provider,
            item.provider_station_id,
            item.provider_channel_id,
            item.pollutant,
            item.unit,
        )

    def snapshot(self) -> AirPollutionRuntimeSnapshot:
        with self._lock:
            return _copy_snapshot(self._snapshot)

    def append_observations(self, observations: list[AirQualityObservation]) -> None:
        if not observations:
            return
        validated = [
            AirQualityObservation.model_validate(item.model_dump(round_trip=True))
            for item in observations
        ]
        newest = max(item.observed_at for item in validated)
        cutoff = newest - timedelta(hours=self.history_hours)
        with self._lock:
            for item in validated:
                series = self._history.setdefault(self._series_key(item), [])
                serialized = item.model_dump_json(round_trip=True)
                if all(existing.model_dump_json(round_trip=True) != serialized for existing in series):
                    series.append(item)
                series[:] = sorted(
                    (sample for sample in series if sample.observed_at >= cutoff),
                    key=lambda sample: sample.observed_at,
                )[-self.max_samples_per_series :]

    def observation_series(self, observation: AirQualityObservation) -> list[AirQualityObservation]:
        with self._lock:
            return [
                AirQualityObservation.model_validate(item.model_dump(round_trip=True))
                for item in self._history.get(self._series_key(observation), [])
            ]

    def replace_events(
        self,
        events: list[StoredAirPollutionEvent],
        *,
        status: Literal["success", "partial"],
        attempted_at: datetime,
        collected_at: datetime,
        observation_count: int,
        excluded_count: int,
        errors: list[str],
    ) -> None:
        attempted = _as_utc(attempted_at)
        collected = _as_utc(collected_at)
        snapshot = AirPollutionRuntimeSnapshot(
            status=status,
            events=[
                StoredAirPollutionEvent.model_validate(item.model_dump(round_trip=True))
                for item in events
            ],
            last_attempted_at=attempted,
            last_successful_collection_at=collected,
            stale=False,
            observation_count=observation_count,
            excluded_count=excluded_count,
            errors=list(dict.fromkeys(errors)),
        )
        with self._lock:
            self._snapshot = snapshot

    def record_failure(self, *, attempted_at: datetime, errors: list[str]) -> None:
        attempted = _as_utc(attempted_at)
        with self._lock:
            prior = self._snapshot
            self._snapshot = AirPollutionRuntimeSnapshot(
                status="failed",
                events=prior.events,
                last_attempted_at=attempted,
                last_successful_collection_at=prior.last_successful_collection_at,
                stale=bool(prior.events),
                observation_count=prior.observation_count,
                excluded_count=prior.excluded_count,
                errors=list(dict.fromkeys(errors or ["air_quality_collection_failed"])),
            )
