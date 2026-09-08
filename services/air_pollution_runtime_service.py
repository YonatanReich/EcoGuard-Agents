"""Refresh EA-308 observations into correlation-ready anomaly candidates."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from agents.air_pollution_anomaly_detector import (
    AirPollutionAnomalyDetector,
    AirQualityReferenceRule,
    DetectionRequest,
    HistoricalBaseline,
)
from agents.air_pollution_correlation import (
    PollutionCorrelationResult,
    compare_pollution_candidates,
    correlation_candidate,
)
from agents.air_pollution_spatial_enrichment import AirPollutionSpatialEnricher
from services.air_pollution_event_store import (
    AirPollutionEventStore,
    StoredAirPollutionEvent,
)
from services.air_quality_schemas import AirQualityObservation
from services.ministry_air_quality_client import MinistryAirQualityClient


DEFAULT_REFRESH_MINUTES = 5


def configured_refresh_minutes() -> int:
    try:
        value = int(os.getenv("AIR_QUALITY_REFRESH_INTERVAL_MINUTES", str(DEFAULT_REFRESH_MINUTES)))
    except ValueError:
        return DEFAULT_REFRESH_MINUTES
    return value if value >= 1 else DEFAULT_REFRESH_MINUTES


ReferenceRuleProvider = Callable[[str, str], Sequence[AirQualityReferenceRule]]


class AirPollutionRuntimeService:
    """Collect and process pollution state independently of browser requests.

    Reference rules remain injected because EA-309 intentionally ships no
    guessed production threshold. A bounded prior-observation series can feed
    EA-309's robust baseline branch; insufficient or zero-dispersion history
    correctly emits no anomaly. A future shared repository can supply longer
    histories, verified rules, and provider AQI evidence here.
    """

    def __init__(
        self,
        *,
        store: AirPollutionEventStore,
        client=None,
        detector=None,
        enricher=None,
        reference_rules: ReferenceRuleProvider | None = None,
        cadence_minutes: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.store = store
        self.client = client if client is not None else MinistryAirQualityClient()
        self.detector = detector if detector is not None else AirPollutionAnomalyDetector()
        self.enricher = enricher if enricher is not None else AirPollutionSpatialEnricher()
        self.reference_rules = reference_rules or (lambda _station, _pollutant: ())
        self.cadence_minutes = (
            cadence_minutes
            if cadence_minutes is not None
            else configured_refresh_minutes()
        )
        if self.cadence_minutes < 1:
            raise ValueError("refresh cadence must be at least one minute")
        self.clock = clock
        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh(self) -> dict:
        if not self._run_lock.acquire(blocking=False):
            return {"status": "skipped_overlap"}
        try:
            attempted_at = self.clock()
            if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
                raise ValueError("runtime clock must return a timezone-aware datetime")
            attempted_at = attempted_at.astimezone(timezone.utc)
            try:
                station_result = self.client.get_station_metadata()
                collection = self.client.collect_latest()
            except Exception:
                self.store.record_failure(
                    attempted_at=attempted_at,
                    errors=["air_quality_provider_failure"],
                )
                return {"status": "failed", "errors": ["air_quality_provider_failure"]}

            if collection.status == "failed":
                errors = collection.errors or ["air_quality_collection_failed"]
                self.store.record_failure(attempted_at=attempted_at, errors=errors)
                return {"status": "failed", "errors": errors}

            self.store.append_observations(collection.observations)
            prior_events = self.store.snapshot().events
            stations = {item.provider_station_id: item for item in station_result.stations}
            results: list[StoredAirPollutionEvent] = []
            errors = list(collection.errors)
            evaluated: set[tuple[str, str, str, str, str]] = set()

            for observation in collection.observations:
                key = (
                    observation.provider,
                    observation.provider_station_id,
                    observation.provider_channel_id,
                    observation.pollutant,
                    observation.unit,
                )
                if key in evaluated:
                    continue
                evaluated.add(key)
                station = stations.get(observation.provider_station_id)
                if station is None:
                    errors.append("station_metadata_unavailable")
                    continue
                monitor = next(
                    (
                        item for item in station.monitors
                        if item.provider_channel_id == observation.provider_channel_id
                    ),
                    None,
                )
                try:
                    series = self.store.observation_series(observation)
                    rules = [
                        rule
                        for rule in self.reference_rules(
                            station.provider_station_id,
                            observation.pollutant,
                        )
                        if rule.effective_from <= attempted_at
                    ]
                    request = DetectionRequest(
                        station_id=station.provider_station_id,
                        station_name=station.name,
                        pollutant=observation.pollutant,
                        location=observation.location,
                        station_active=station.active,
                        channel_active=monitor.active if monitor is not None else None,
                        observations=series,
                        reference_rules=rules,
                        historical_baseline=self._historical_baseline(
                            observation,
                            series,
                        ),
                    )
                    anomaly = self.detector.detect(request, detected_at=attempted_at)
                except Exception:
                    errors.append("air_pollution_detection_failed")
                    continue
                if anomaly is None:
                    continue

                try:
                    enriched = self.enricher.enrich(anomaly)
                    candidate = correlation_candidate(enriched)
                except Exception:
                    candidate = correlation_candidate(anomaly)
                    errors.append("air_pollution_spatial_enrichment_failed")

                correlation = self._closest_prior_match(candidate, prior_events)
                results.append(
                    StoredAirPollutionEvent(
                        event=candidate,
                        correlation_evidence=correlation,
                    )
                )

            status = "partial" if collection.status == "partial" or errors else "success"
            self.store.replace_events(
                results,
                status=status,
                attempted_at=attempted_at,
                collected_at=collection.collected_at,
                observation_count=len(collection.observations),
                excluded_count=len(collection.excluded),
                errors=errors,
            )
            return {
                "status": status,
                "observations": len(collection.observations),
                "events": len(results),
                "excluded": len(collection.excluded),
            }
        finally:
            self._run_lock.release()

    @staticmethod
    def _historical_baseline(
        current: AirQualityObservation,
        series: list[AirQualityObservation],
    ) -> HistoricalBaseline | None:
        """Build comparable prior-value evidence; no thresholds or filling.

        Conflicting duplicate timestamps are excluded. EA-309 still decides
        whether the history is sufficient and whether its robust MAD branch
        constitutes anomaly evidence.
        """
        by_time: dict[datetime, list[AirQualityObservation]] = {}
        for item in series:
            if item.observed_at < current.observed_at:
                by_time.setdefault(item.observed_at, []).append(item)
        comparable = [
            items[0]
            for _, items in sorted(by_time.items())
            if len(items) == 1
        ]
        if len(comparable) < 20:
            return None
        return HistoricalBaseline(
            station_id=current.provider_station_id,
            pollutant=current.pollutant,
            unit=current.unit,
            values=[item.value for item in comparable],
            ended_at=comparable[-1].observed_at,
            source=f"{current.provider} normalized prior observations",
            version="runtime-robust-baseline-v1",
        )

    @staticmethod
    def _closest_prior_match(candidate, prior_events) -> PollutionCorrelationResult | None:
        matches = []
        for prior in prior_events:
            try:
                comparison = compare_pollution_candidates(candidate, prior.event)
            except Exception:
                continue
            if comparison.candidate_match:
                matches.append(comparison)
        if not matches:
            return None
        return min(
            matches,
            key=lambda item: (item.temporal_distance_seconds, item.spatial_distance_km),
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="air-quality-refresh",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        self._refresh_safely()
        interval_seconds = self.cadence_minutes * 60
        while not self._stop.wait(interval_seconds):
            self._refresh_safely()

    def _refresh_safely(self) -> None:
        try:
            self.refresh()
        except Exception:
            # A malformed local dependency must not kill future scheduled
            # collection attempts or leak provider/model exception details.
            self.store.record_failure(
                attempted_at=datetime.now(timezone.utc),
                errors=["air_pollution_refresh_failed"],
            )
