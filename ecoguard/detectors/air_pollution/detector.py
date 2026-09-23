"""Exact five-minute-baseline Air Pollution candidate detector."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from datetime import datetime, timezone

from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics,
    LiveBaselineContextResult,
)

from ecoguard.detectors.air_pollution.schemas import (
    DETECTOR_BASELINE_FAMILY,
    DETECTOR_RULE_VERSION,
    AirPollutionAnomaly,
    AirPollutionBaselineEvidence,
    AirPollutionDetectionResult,
)

CandidateRule = Callable[[float, BaselineBucketStatistics], bool]


def live_value_above_p95(value: float, baseline: BaselineBucketStatistics) -> bool:
    """Versioned candidate rule, isolated from the detector contract."""

    return value > baseline.p95


class AirPollutionAnomalyDetector:
    """Classify an already-resolved live/baseline context without side effects."""

    def __init__(
        self,
        *,
        rule: CandidateRule = live_value_above_p95,
        rule_version: str = DETECTOR_RULE_VERSION,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """Build a detector. The comparison rule is injectable for testing."""
        self._rule = rule
        self._rule_version = rule_version
        self._clock = clock

    def detect(self, context: LiveBaselineContextResult) -> AirPollutionDetectionResult:
        """Decide whether one reading is above its own baseline.

        Returns a result either way: an anomaly, a reasoned no, or a statement
        that it could not be evaluated. It never guesses when the baseline is
        missing or incomplete.
        """
        if not isinstance(context, LiveBaselineContextResult):
            return self._not_evaluated("invalid_observation")
        if context.status != "available" or not context.comparison_eligible:
            return self._not_evaluated(self._unavailable_reason(context), context)

        live = context.live_observation
        identity = context.lookup_identity
        statistics = context.baseline_statistics
        version = context.baseline_version
        if live is None or identity is None or statistics is None or version is None:
            return self._not_evaluated("incomplete_baseline_context", context)
        if identity.baseline_family != DETECTOR_BASELINE_FAMILY:
            return self._not_evaluated("baseline_family_mismatch", context)
        if (
            live.provider,
            live.station_id,
            live.channel_id,
            live.pollutant,
        ) != (
            identity.provider,
            identity.station_id,
            identity.channel_id,
            identity.pollutant,
        ):
            return self._not_evaluated("identity_mismatch", context)
        if live.unit_source != "reading" or live.measurement_unit != identity.canonical_unit:
            return self._not_evaluated("unit_mismatch", context)
        if (
            statistics.status != "ok"
            or statistics.p95 is None
            or not math.isfinite(statistics.p95)
        ):
            return self._not_evaluated("insufficient_history", context)
        if context.month is None or context.hour is None:
            return self._not_evaluated("incomplete_baseline_context", context)

        evidence = AirPollutionBaselineEvidence(
            identity=identity,
            month=context.month,
            hour=context.hour,
            statistics=statistics,
            version=version,
        )
        common = {
            "detector_rule_version": self._rule_version,
            "live_observation": live,
            "baseline_evidence": evidence,
            "context_reason": context.reason,
        }
        if not self._rule(live.value, statistics):
            return AirPollutionDetectionResult(
                status="NORMAL",
                reason="live_value_at_or_below_baseline_p95",
                **common,
            )

        detected_at = self._clock()
        if detected_at.utcoffset() is None:
            return self._not_evaluated("invalid_detector_clock", context)
        detected_at = detected_at.astimezone(timezone.utc)
        if detected_at < live.observed_at:
            return self._not_evaluated("detector_clock_precedes_observation", context)

        anomaly = self._build_anomaly(context, evidence, detected_at)
        return AirPollutionDetectionResult(
            status="SUSPECTED_ANOMALY",
            reason="live_value_above_baseline_p95",
            anomaly=anomaly,
            **common,
        )

    def _not_evaluated(
        self,
        reason: str,
        context: LiveBaselineContextResult | None = None,
    ) -> AirPollutionDetectionResult:
        """A result saying the reading could not be judged, and why."""
        return AirPollutionDetectionResult(
            status="NOT_EVALUATED",
            reason=reason,
            detector_rule_version=self._rule_version,
            live_observation=context.live_observation if context else None,
            context_reason=context.reason if context else None,
        )

    @staticmethod
    def _unavailable_reason(context: LiveBaselineContextResult) -> str:
        """Why no baseline was usable for this reading."""
        if context.status == "insufficient_history":
            return "insufficient_history"
        if context.status in {
            "profile_unavailable",
            "baseline_unavailable",
            "bucket_unavailable",
        }:
            return "baseline_unavailable"
        return context.eligibility_reason or context.reason or "lookup_unavailable"

    def _build_anomaly(
        self,
        context: LiveBaselineContextResult,
        evidence: AirPollutionBaselineEvidence,
        detected_at: datetime,
    ) -> AirPollutionAnomaly:
        """The anomaly record, carrying the reading and the baseline it beat."""
        live = context.live_observation
        material = "|".join(
            (
                live.provider,
                live.station_id,
                live.channel_id,
                live.pollutant,
                live.measurement_unit,
                live.observed_at.isoformat(),
                str(evidence.version.baseline_version_id),
                self._rule_version,
            )
        )
        detection_id = "air-pollution:" + hashlib.sha256(
            material.encode("utf-8")
        ).hexdigest()[:32]
        return AirPollutionAnomaly(
            detection_id=detection_id,
            observed_at=live.observed_at,
            detected_at=detected_at,
            location=live.location,
            provider=live.provider,
            station_id=live.station_id,
            station_name=context.station_name,
            channel_id=live.channel_id,
            pollutant=live.pollutant,
            value=live.value,
            unit=live.measurement_unit,
            live_observation=live,
            detector_reason="live_value_above_baseline_p95",
            detector_rule_version=self._rule_version,
            baseline_evidence=evidence,
        )
