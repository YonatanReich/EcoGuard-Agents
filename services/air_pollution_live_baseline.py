"""Live reading to exact baseline context; no scoring, fallback, or writes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

from pydantic import ValidationError

from services.air_pollution_baseline_lookup import AirPollutionBaselineLookupService
from services.air_pollution_baseline_schemas import (
    BaselineIdentity,
    BaselineLookupRequest,
    LiveBaselineContextResult,
    LiveObservationContext,
)
from services.air_pollution_hourly import provider_hour_for_observation
from services.air_quality_schemas import (
    AirQualityObservation,
    LIVE_QUALITY_POLICY,
)

BASELINE_POLLUTANTS = frozenset({"NO2", "O3", "PM10", "PM2.5", "SO2"})
LIVE_BASELINE_FAMILY = "five_minute_observation"


class AirPollutionLiveBaselineContextService:
    """Resolve exact context for one preliminary five-minute live reading."""

    def __init__(self, baseline_lookup: AirPollutionBaselineLookupService | None = None):
        self.baseline_lookup = baseline_lookup or AirPollutionBaselineLookupService()

    def lookup(self, observation: AirQualityObservation | Mapping[str, Any]):
        """Operational path: delegates only to active-only baseline lookup."""
        return self._resolve(observation, mode="operational", baseline_version_id=None)

    def lookup_draft_for_validation(
        self,
        observation: AirQualityObservation | Mapping[str, Any],
        *,
        baseline_version_id: int | None = None,
    ):
        """Explicit validation path; never selected by the operational method."""
        return self._resolve(
            observation,
            mode="draft_validation",
            baseline_version_id=baseline_version_id,
        )

    def lookup_batch(
        self,
        observations: Iterable[AirQualityObservation | Mapping[str, Any]],
    ) -> list[LiveBaselineContextResult]:
        """Resolve active-only contexts in input order through one batch read."""
        return self._resolve_batch(observations, mode="operational")

    def lookup_draft_batch_for_validation(
        self,
        observations: Iterable[AirQualityObservation | Mapping[str, Any]],
    ) -> list[LiveBaselineContextResult]:
        """Resolve draft-only contexts explicitly for validation/benchmarking."""
        return self._resolve_batch(observations, mode="draft_validation")

    @staticmethod
    def _invalid(mode: str, reason: str) -> LiveBaselineContextResult:
        return LiveBaselineContextResult(
            status="invalid_live_observation",
            reason=reason,
            eligibility_reason=reason,
            mode=mode,
        )

    def _resolve(self, observation, *, mode, baseline_version_id):
        prepared = self._prepare(observation, mode=mode)
        if isinstance(prepared, LiveBaselineContextResult):
            return prepared
        live, context, identity, month, hour = prepared
        if mode == "operational":
            lookup = self.baseline_lookup.lookup(identity, month=month, hour=hour)
        else:
            lookup = self.baseline_lookup.lookup_draft_for_validation(
                identity, month=month, hour=hour,
                baseline_version_id=baseline_version_id,
            )
        return self._context_result(
            mode=mode, live_context=context, identity=identity,
            month=month, hour=hour, lookup=lookup,
        )

    def _resolve_batch(self, observations, *, mode):
        supplied = list(observations)
        results: list[LiveBaselineContextResult | None] = [None] * len(supplied)
        prepared_items = []
        requests = []
        for input_index, observation in enumerate(supplied):
            prepared = self._prepare(observation, mode=mode)
            if isinstance(prepared, LiveBaselineContextResult):
                results[input_index] = prepared
                continue
            live, context, identity, month, hour = prepared
            prepared_items.append((input_index, context, identity, month, hour))
            requests.append(BaselineLookupRequest(
                identity=identity, month=month, hour=hour,
            ))

        if mode == "operational":
            lookups = self.baseline_lookup.lookup_batch(requests)
        else:
            lookups = self.baseline_lookup.lookup_draft_batch_for_validation(requests)
        if len(lookups) != len(prepared_items):
            raise RuntimeError("baseline batch lookup returned an invalid result count")
        for (input_index, context, identity, month, hour), lookup in zip(
            prepared_items, lookups, strict=True,
        ):
            results[input_index] = self._context_result(
                mode=mode, live_context=context, identity=identity,
                month=month, hour=hour, lookup=lookup,
            )
        if any(result is None for result in results):
            raise RuntimeError("live baseline batch did not preserve every input")
        return cast(list[LiveBaselineContextResult], results)

    def _prepare(self, observation, *, mode):
        raw = (
            observation.model_dump(mode="python")
            if isinstance(observation, AirQualityObservation)
            else observation
        )
        if not isinstance(raw, Mapping):
            return self._invalid(mode, "malformed_live_observation")
        if not isinstance(raw.get("provider_channel_id"), str) or not raw.get(
            "provider_channel_id", ""
        ).strip():
            return self._invalid(mode, "missing_channel_id")
        if raw.get("unit_source") != "reading":
            return self._invalid(mode, "measurement_unit_not_reading_supplied")
        if not raw.get("measurement_unit") or not raw.get("reading_unit"):
            return self._invalid(mode, "missing_measurement_unit_provenance")
        if raw.get("unit") != raw.get("measurement_unit"):
            return self._invalid(mode, "incompatible_measurement_unit")
        try:
            live = AirQualityObservation.model_validate(raw)
        except ValidationError:
            return self._invalid(mode, "malformed_live_observation")
        if live.pollutant not in BASELINE_POLLUTANTS:
            return self._invalid(mode, "unsupported_baseline_pollutant")
        if live.quality_policy != LIVE_QUALITY_POLICY:
            return self._invalid(mode, "incompatible_quality_policy")
        try:
            provider_hour = provider_hour_for_observation(
                live.observed_at, live.provider_timestamp,
            )
        except (TypeError, ValueError):
            return self._invalid(mode, "provider_clock_incompatible")

        identity = BaselineIdentity(
            provider=live.provider,
            station_id=live.provider_station_id,
            channel_id=live.provider_channel_id,
            pollutant=live.pollutant,
            canonical_unit=live.measurement_unit,
            baseline_family=LIVE_BASELINE_FAMILY,
        )
        context = LiveObservationContext(
            provider=live.provider,
            station_id=live.provider_station_id,
            channel_id=live.provider_channel_id,
            pollutant=live.pollutant,
            value=live.value,
            observed_at=live.observed_at,
            provider_timestamp=live.provider_timestamp,
            measurement_unit=live.measurement_unit,
            unit_source="reading",
            reading_unit=live.reading_unit,
            location=live.location,
        )
        return live, context, identity, provider_hour.month, provider_hour.hour

    @staticmethod
    def _context_result(
        *, mode, live_context, identity, month, hour, lookup,
    ) -> LiveBaselineContextResult:
        comparison_eligible = lookup.status == "available"
        reason = lookup.reason
        return LiveBaselineContextResult(
            status=lookup.status,
            reason=reason,
            mode=mode,
            live_observation=live_context,
            station_name=lookup.station_name,
            lookup_identity=identity,
            month=month,
            hour=hour,
            lookup_status=lookup.status,
            baseline_statistics=lookup.bucket,
            baseline_version=lookup.version,
            comparison_eligible=comparison_eligible,
            eligibility_reason=reason,
        )
