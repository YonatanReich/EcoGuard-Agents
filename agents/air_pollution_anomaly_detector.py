"""Deterministic, storage- and provider-independent air-pollution detector.

The detector consumes an injected series for one station and pollutant. It does
not fetch data, perform spatial correlation, or make emergency/response
decisions. Reference rules are caller-supplied and versioned; this module ships
no unverified legal thresholds.

Call ``detect(DetectionRequest(...), detected_at=aware_utc_time)`` for one
station/channel/pollutant. References and sustained thresholds are opt-in.
``evaluate_reference_window`` also exposes non-triggering/provisional results.
Rolling means assume interval-ending, equally spaced normalized measurements;
they do not certify calendar-day regulatory compliance. Baselines must contain
comparable earlier single-observation values (same station, pollutant and unit).
The confidence rubric and severity mapping are engineering policy version 1,
not Ministry classifications or calibrated probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import median
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import AwareDatetime, Field, field_validator, model_validator

from agents.air_pollution_anomaly_schemas import (
    AirPollutionAnomaly,
    AnomalySource,
    ContractModel,
    DetectionAssessment,
    DetectionMethod,
    GeographicCoordinate,
    PollutantObservation,
    PollutantUnit,
    SupportingEvidence,
)
from services.air_quality_schemas import AirQualityObservation

ReferenceKind = Literal["target", "environmental", "alert", "other"]


class AirQualityReferenceRule(ContractModel):
    """A caller-supplied, versioned concentration reference."""

    rule_id: str = Field(min_length=1, max_length=200)
    pollutant: str = Field(min_length=1, max_length=32)
    reference_kind: ReferenceKind
    value: float = Field(ge=0, strict=True)
    unit: PollutantUnit
    averaging_minutes: int = Field(gt=0)
    source: str = Field(min_length=1, max_length=500)
    effective_from: AwareDatetime
    source_version: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, min_length=1, max_length=1000)


class ProviderAQIEvidence(ContractModel):
    """Index as received, with an explicit caller-configured trigger decision.

    ``anomalous`` must come from provider classification or a documented caller
    policy; ``interpretation_source`` records which. No breakpoints are guessed.
    """

    provider: str = Field(min_length=1, max_length=200)
    station_id: str = Field(min_length=1, max_length=200)
    value: float = Field(strict=True)
    category: str = Field(min_length=1, max_length=100)
    observed_at: AwareDatetime
    anomalous: bool = Field(strict=True)
    interpretation_source: str = Field(min_length=1, max_length=500)
    pollutant_sub_index: float | None = Field(default=None, strict=True)
    pollutant: str | None = Field(default=None, min_length=1, max_length=32)


class HistoricalBaseline(ContractModel):
    """Injected comparable historical values for robust MAD evaluation."""

    station_id: str = Field(min_length=1, max_length=200)
    pollutant: str = Field(min_length=1, max_length=32)
    unit: PollutantUnit
    values: list[Annotated[float, Field(strict=True, ge=0)]]
    ended_at: AwareDatetime
    minimum_samples: int = Field(default=20, ge=3)
    mad_multiplier: float = Field(default=4.0, gt=0)
    source: str = Field(min_length=1, max_length=500)
    version: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("values")
    @classmethod
    def _valid_values(cls, values: list[float]) -> list[float]:
        if any(value < 0 for value in values):
            raise ValueError("baseline values must be non-negative")
        return values


class DetectorConfig(ContractModel):
    """EcoGuard engineering controls, not Ministry rules."""

    sampling_interval_minutes: int = Field(default=5, gt=0)
    minimum_completeness: float = Field(default=0.75, gt=0, le=1)
    freshness_intervals: float = Field(default=2.0, gt=0)
    sustained_value_threshold: float | None = Field(default=None, ge=0, strict=True)
    sustained_unit: PollutantUnit | None = None
    minimum_consecutive_observations: int = Field(default=3, ge=2)
    minimum_persistence_minutes: int = Field(default=10, ge=0)
    strong_increase_fraction: float | None = Field(default=None, gt=0)
    preliminary_confidence_cap: float = Field(default=0.85, gt=0, lt=1)

    @model_validator(mode="after")
    def _threshold_unit(self) -> "DetectorConfig":
        if self.sustained_value_threshold is not None and self.sustained_unit is None:
            raise ValueError("sustained_unit is required with sustained_value_threshold")
        return self


class DetectionRequest(ContractModel):
    station_id: str = Field(min_length=1, max_length=200)
    station_name: str = Field(min_length=1, max_length=300)
    pollutant: str = Field(min_length=1, max_length=32)
    location: GeographicCoordinate
    station_active: bool | None = None
    channel_active: bool | None = None
    observations: list[AirQualityObservation] = Field(default_factory=list)
    reference_rules: list[AirQualityReferenceRule] = Field(default_factory=list)
    provider_aqi: ProviderAQIEvidence | None = None
    historical_baseline: HistoricalBaseline | None = None

    @model_validator(mode="after")
    def _consistent_series(self) -> "DetectionRequest":
        if len({(item.provider, item.provider_channel_id, item.unit) for item in self.observations}) > 1:
            raise ValueError("supply one provider/channel/unit series per request; no unit conversion")
        for observation in self.observations:
            if observation.provider_station_id != self.station_id:
                raise ValueError("all observations must belong to station_id")
            if observation.pollutant != self.pollutant:
                raise ValueError("all observations must use the requested pollutant")
            if observation.location != self.location:
                raise ValueError("all observations must use the requested station location")
        for rule in self.reference_rules:
            if rule.pollutant != self.pollutant:
                raise ValueError("reference rule pollutant does not match request")
        if len({rule.rule_id for rule in self.reference_rules}) != len(self.reference_rules):
            raise ValueError("reference rule IDs must be unique")
        if len(self.reference_rules) > 16:
            raise ValueError("at most 16 reference rules per evaluation")
        for evidence in (self.provider_aqi, self.historical_baseline):
            if evidence is not None and (
                evidence.station_id != self.station_id
                or evidence.pollutant not in (None, self.pollutant)
            ):
                raise ValueError("AQI/baseline station and pollutant must match request")
        return self


@dataclass(frozen=True)
class ReferenceWindowResult:
    """Sample mean over (start, end]; completeness is not legal certification.

    One sample represents one configured collection interval ending at its
    timestamp. Non-integral windows and irregular cadence are unevaluable;
    missing samples are never filled. ``complete`` means full temporal span
    and sufficient configured coverage, not 100% coverage or validated data.
    """
    rule: AirQualityReferenceRule
    observations: tuple[AirQualityObservation, ...]
    average: float | None
    expected: int
    completeness: float
    complete: bool
    exceeded: bool
    started_at: datetime
    ended_at: datetime
    limitation: str | None = None


class AirPollutionAnomalyDetector:
    """Evaluate injected observations and return an EA-307 anomaly or ``None``."""

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()

    def detect(
        self,
        request: DetectionRequest,
        *,
        detected_at: datetime | None = None,
    ) -> AirPollutionAnomaly | None:
        # Revalidate even model_copy/model_construct inputs before evaluating.
        request = DetectionRequest.model_validate(request.model_dump())
        now = detected_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("detected_at must have a timezone")
        now = now.astimezone(timezone.utc)
        if request.station_active is False or request.channel_active is False:
            return None
        series, excluded_count = self._clean_series(request.observations, now)
        if not series:
            return None
        latest = series[-1]
        if any(latest.observed_at < item.observed_at <= now for item in request.observations):
            # A later invalid sample breaks the current run, even if an older
            # clean sample is still inside the freshness allowance.
            return None
        freshness = max((now - latest.observed_at).total_seconds(), 0.0)
        stale = freshness > (
            self.config.sampling_interval_minutes
            * self.config.freshness_intervals
            * 60
        )
        if stale:
            return None

        windows = tuple(self.evaluate_reference_window(rule, series) for rule in request.reference_rules)
        exceeded = tuple(item for item in windows if item.exceeded)
        sustained, increasing = self._sustained(series)
        baseline = self._baseline(latest, request.historical_baseline)
        aqi = request.provider_aqi
        aqi_fresh = bool(aqi and 0 <= (now - aqi.observed_at).total_seconds() <= (
            self.config.sampling_interval_minutes * self.config.freshness_intervals * 60
        ))
        aqi_trigger = bool(aqi and aqi.anomalous and aqi_fresh)

        methods: list[DetectionMethod] = []
        if exceeded:
            methods.append("reference_threshold")
        if aqi_trigger:
            methods.append("provider_aqi")
        if sustained:
            methods.append("sustained_condition")
        if baseline["anomalous"]:
            methods.append("historical_baseline")
        if not methods:
            return None

        reasons = self._reasons(request.pollutant, exceeded, sustained, increasing, aqi_trigger, baseline)
        limitations: list[str] = []
        incomplete = [item for item in windows if not item.complete]
        if incomplete:
            limitations.append("One or more reference windows were incomplete and were not treated as exceedances.")
        limitations.extend(item.limitation for item in windows if item.limitation)
        if excluded_count:
            limitations.append(f"Excluded {excluded_count} readings with unusable status, future time or conflicting duplicates.")
        if aqi and not aqi_fresh:
            limitations.append("Provider AQI is stale or future-dated and did not trigger detection.")
        if self.config.sustained_value_threshold is not None and latest.unit != self.config.sustained_unit:
            limitations.append("Sustained-rule unit mismatch; no comparison or conversion performed.")
        preliminary = all(item.quality_control == "preliminary_unvalidated" for item in series)
        if preliminary:
            limitations.append("Input measurements are preliminary and have not completed provider quality control.")
        if request.historical_baseline is None:
            limitations.append("No historical baseline was supplied.")
        elif not baseline["sufficient"]:
            limitations.append("Historical baseline was insufficient, incompatible, overlapping, or had zero dispersion.")

        confidence, factors, caps = self._confidence(
            exceeded=exceeded,
            sustained=sustained,
            preliminary=preliminary,
            aqi_trigger=aqi_trigger,
            baseline_trigger=bool(baseline["anomalous"]),
            sample_count=sum(
                latest.observed_at - item.observed_at < timedelta(
                    minutes=self.config.sampling_interval_minutes
                    * self.config.minimum_consecutive_observations
                )
                for item in series
            ),
            incomplete=bool(incomplete),
            baseline_insufficient=not baseline["sufficient"],
            excluded_count=excluded_count,
        )
        primary_window = exceeded[0] if exceeded else (windows[0] if windows else None)
        observations = [
            PollutantObservation(
                pollutant=item.pollutant,
                provider_pollutant_id=item.provider_pollutant_id,
                value=item.value,
                unit=item.unit,
                provider_unit=item.provider_unit,
                observed_at=item.observed_at,
                source_id=item.provider,
            )
            for item in series
        ]
        evidence = self._evidence(request, windows, sustained, increasing, baseline)
        source = AnomalySource(
            source_id=latest.provider,
            source_name="Normalized air-quality observation source",
            source_type="ground_monitoring_network",
            observed_at=latest.observed_at,
            metadata={
                "station_id": request.station_id,
                "station_name": request.station_name,
                "channel_id": latest.provider_channel_id,
                "excluded_count": excluded_count,
                "quality_control": latest.quality_control,
            },
        )
        if request.provider_aqi:
            evidence.append(
                SupportingEvidence(
                    evidence_id=f"provider-aqi:{request.station_id}:{request.provider_aqi.observed_at.isoformat()}",
                    source_id=request.provider_aqi.provider,
                    evidence_type="provider_aqi",
                    summary="Provider AQI was preserved as received; EcoGuard did not recalculate it.",
                    observed_at=request.provider_aqi.observed_at,
                    attributes={
                        "value": request.provider_aqi.value,
                        "category": request.provider_aqi.category,
                        "anomalous_as_supplied": request.provider_aqi.anomalous,
                        "pollutant_sub_index": request.provider_aqi.pollutant_sub_index,
                        "pollutant": request.provider_aqi.pollutant,
                        "interpretation_source": request.provider_aqi.interpretation_source,
                        "fresh": aqi_fresh,
                        "triggered": aqi_trigger,
                    },
                )
            )

        # Every evidence source is resolvable within the EA-307 source list.
        sources = {source.source_id: source}
        for item in evidence:
            if item.source_id not in sources:
                sources[item.source_id] = AnomalySource(
                    source_id=item.source_id, source_name=item.source_id,
                )
        identity = request.model_dump_json() + self.config.model_dump_json() + now.isoformat()
        return AirPollutionAnomaly(
            detection_id=f"air-pollution:{uuid5(NAMESPACE_URL, identity)}",
            observed_at=latest.observed_at,
            detected_at=now,
            location=request.location,
            pollutant_observations=observations,
            severity=self._severity(methods, exceeded),
            confidence=confidence,
            explanation="; ".join(reasons),
            anomaly_reasons=reasons,
            sources=list(sources.values()),
            supporting_evidence=evidence,
            assessment=DetectionAssessment(
                detection_methods=methods,
                window_started_at=primary_window.started_at if primary_window else series[0].observed_at,
                window_ended_at=primary_window.ended_at if primary_window else latest.observed_at,
                aggregation_minutes=primary_window.rule.averaging_minutes if primary_window else None,
                valid_sample_count=len(primary_window.observations) if primary_window else len(series),
                expected_sample_count=primary_window.expected if primary_window else None,
                completeness_ratio=primary_window.completeness if primary_window else None,
                window_complete=primary_window.complete if primary_window else None,
                reference_kind=primary_window.rule.reference_kind if primary_window else None,
                reference_value=primary_window.rule.value if primary_window else None,
                reference_unit=primary_window.rule.unit if primary_window else None,
                reference_source=primary_window.rule.source if primary_window else None,
                reference_version=primary_window.rule.source_version if primary_window else None,
                provider_aqi_value=request.provider_aqi.value if request.provider_aqi else None,
                provider_aqi_category=request.provider_aqi.category if request.provider_aqi else None,
                baseline_median=baseline["median"],
                baseline_deviation=baseline["deviation"],
                freshness_seconds=freshness,
                preliminary=preliminary,
                limitations=limitations,
                confidence_factors=factors,
                confidence_caps=caps,
            ),
        )

    @staticmethod
    def _clean_series(observations, now):
        """Exclude conflicting timestamps, preserve gaps, collapse exact repeats."""
        by_time: dict[datetime, list[AirQualityObservation]] = {}
        excluded = 0
        for item in observations:
            by_time.setdefault(item.observed_at, []).append(item)
        series = []
        unusable = {"NODATA", "DOWN", "INVLD", "INVALID", "CALIB", "CALIBRATION"}
        for timestamp, items in sorted(by_time.items()):
            if (
                timestamp > now
                or any((item.provider_status or "").strip().upper() in unusable for item in items)
                or len({item.value for item in items}) > 1
            ):
                excluded += len(items)
            else:
                series.append(items[0])
        return tuple(series), excluded

    def evaluate_reference_window(
        self,
        rule: AirQualityReferenceRule,
        series: tuple[AirQualityObservation, ...],
    ) -> ReferenceWindowResult:
        """Inspect an exact rule window even when it does not emit an anomaly.

        Expects a nonempty, normalized single-channel sequence, as detect does.
        Future timestamps cannot be assessed here without a caller's clock.
        """
        if not series:
            raise ValueError("a nonempty series is required to anchor the window")
        rule = AirQualityReferenceRule.model_validate(rule.model_dump())
        series = tuple(sorted(
            (AirQualityObservation.model_validate(item.model_dump()) for item in series),
            key=lambda item: item.observed_at,
        ))
        if len({(item.provider, item.provider_station_id, item.provider_channel_id, item.pollutant, item.unit) for item in series}) != 1:
            raise ValueError("reference window requires a single station/channel/pollutant/unit series")
        series, _ = self._clean_series(series, series[-1].observed_at)
        if not series:
            raise ValueError("no usable samples to anchor the window")
        end = series[-1].observed_at
        start = end - timedelta(minutes=rule.averaging_minutes)
        selected = tuple(item for item in series if start < item.observed_at <= end)
        expected = max(1, ceil(rule.averaging_minutes / self.config.sampling_interval_minutes))
        completeness = min(len(selected) / expected, 1.0)
        span_complete = bool(selected) and selected[0].observed_at <= (
            start + timedelta(minutes=self.config.sampling_interval_minutes)
        )
        cadence_seconds = self.config.sampling_interval_minutes * 60
        cadence_matches = all(
            (end - item.observed_at).total_seconds() % cadence_seconds == 0
            for item in selected
        )
        period_matches = rule.averaging_minutes % self.config.sampling_interval_minutes == 0
        complete = (
            completeness >= self.config.minimum_completeness
            and span_complete and cadence_matches and period_matches
        )
        average = sum(item.value for item in selected) / len(selected) if selected else None
        unit_matches = all(item.unit == rule.unit for item in selected)
        effective = rule.effective_from <= start
        pollutant_matches = all(item.pollutant == rule.pollutant for item in selected)
        limitation = None
        if not unit_matches or not pollutant_matches:
            limitation = "Reference pollutant/unit mismatch; no comparison or conversion performed."
        elif not effective:
            limitation = "Reference was not effective throughout the window."
        elif not cadence_matches or not period_matches:
            limitation = "Sampling cadence cannot represent the exact reference period."
        exceeded = bool(complete and limitation is None and average is not None and average > rule.value)
        return ReferenceWindowResult(rule, selected, average, expected, completeness, complete, exceeded, start, end, limitation)

    def _sustained(self, series: tuple[AirQualityObservation, ...]) -> tuple[bool, bool]:
        threshold = self.config.sustained_value_threshold
        needed = self.config.minimum_consecutive_observations
        if threshold is None or len(series) < needed or series[-1].unit != self.config.sustained_unit:
            return False, False
        # Use the entire contiguous elevated suffix so a longer persistence
        # requirement can be met without increasing the minimum sample count.
        tail = [series[-1]] if series[-1].value >= threshold else []
        cadence = timedelta(minutes=self.config.sampling_interval_minutes)
        for item in reversed(series[:-1]):
            if not tail or tail[-1].observed_at - item.observed_at != cadence or item.value < threshold:
                break
            tail.append(item)
        tail.reverse()
        if len(tail) < needed:
            return False, False
        duration = (tail[-1].observed_at - tail[0].observed_at).total_seconds() / 60
        elevated = all(item.value >= threshold for item in tail)
        monotonic = all(right.value >= left.value for left, right in zip(tail, tail[1:]))
        fraction = (tail[-1].value - tail[0].value) / tail[0].value if tail[0].value > 0 else 0
        strongly_increasing = bool(
            monotonic
            and self.config.strong_increase_fraction is not None
            and fraction >= self.config.strong_increase_fraction
        )
        satisfied = elevated and duration >= self.config.minimum_persistence_minutes
        return satisfied, satisfied and strongly_increasing

    @staticmethod
    def _baseline(current: AirQualityObservation, baseline: HistoricalBaseline | None) -> dict[str, float | bool | None]:
        if (
            baseline is None or len(baseline.values) < baseline.minimum_samples
            or baseline.unit != current.unit or baseline.ended_at >= current.observed_at
        ):
            return {"sufficient": False, "anomalous": False, "median": None, "deviation": None, "mad": None}
        center = median(baseline.values)
        mad = median(abs(value - center) for value in baseline.values)
        deviation = max(current.value - center, 0.0)
        if mad == 0:
            return {"sufficient": False, "anomalous": False, "median": center, "deviation": deviation, "mad": 0.0}
        return {
            "sufficient": True,
            "anomalous": current.value > center + baseline.mad_multiplier * mad,
            "median": center,
            "deviation": deviation,
            "mad": mad,
        }

    @staticmethod
    def _reasons(pollutant, exceeded, sustained, increasing, aqi_trigger, baseline) -> list[str]:
        reasons = [
            f"Completed {item.rule.reference_kind} reference window exceeded for {pollutant}."
            for item in exceeded
        ]
        if sustained:
            reasons.append(f"Sustained {pollutant} elevation met the configured EcoGuard persistence rule.")
        if increasing:
            reasons.append(f"{pollutant} showed a configured strong increasing trend; trend is supporting evidence only.")
        if aqi_trigger:
            reasons.append("Provider AQI evidence was marked anomalous by the supplying provider/context.")
        if baseline["anomalous"]:
            reasons.append(f"{pollutant} was unusually high relative to the supplied station baseline.")
        return reasons

    def _confidence(
        self, *, exceeded, sustained, preliminary, aqi_trigger,
        baseline_trigger, sample_count, incomplete, baseline_insufficient,
        excluded_count,
    ):
        """Version 1 engineering rubric, not a calibrated probability.

        Add named evidence contributions, subtract explicit limitations, then
        apply caps. AQI and raw branches may share measurements, so there is
        no independence bonus. Critical severity is also no emergency decision.
        """
        factors: dict[str, float] = {"fresh_valid_input": 0.30}
        if exceeded:
            factors["completed_reference_window"] = 0.30 * min(item.completeness for item in exceeded)
        if sustained:
            factors["persistence"] = 0.20
        if aqi_trigger:
            factors["provider_aqi_support"] = 0.15
        if baseline_trigger:
            factors["robust_baseline"] = 0.15
        if incomplete:
            factors["incomplete_window_penalty"] = -0.05
        if baseline_insufficient:
            factors["unavailable_baseline_penalty"] = -0.05
        if excluded_count:
            factors["excluded_reading_penalty"] = -0.05
        caps = {"uncalibrated_engineering_confidence": 0.95}
        if sample_count < self.config.minimum_consecutive_observations:
            caps["isolated_or_short_series"] = 0.45
        if preliminary:
            factors["preliminary_data_penalty"] = -0.05
            caps["preliminary_data"] = self.config.preliminary_confidence_cap
        confidence = min(max(sum(factors.values()), 0.0), *caps.values())
        return round(confidence, 4), factors, caps

    @staticmethod
    def _severity(methods, exceeded) -> str:
        if any(item.rule.reference_kind == "alert" for item in exceeded):
            return "critical"
        if any(item.rule.reference_kind == "environmental" for item in exceeded):
            return "high"
        if len(methods) >= 2:
            return "high"
        return "medium"

    def _evidence(self, request, windows, sustained, increasing, baseline) -> list[SupportingEvidence]:
        evidence: list[SupportingEvidence] = []
        for result in windows:
            evidence.append(
                SupportingEvidence(
                    evidence_id=f"rule:{result.rule.rule_id}:{result.ended_at.isoformat()}",
                    source_id=result.rule.source,
                    evidence_type="reference_window",
                    summary=f"{result.rule.reference_kind.title()} reference evaluated using its configured window.",
                    observed_at=result.ended_at,
                    attributes={
                        "rule_id": result.rule.rule_id,
                        "reference_kind": result.rule.reference_kind,
                        "reference_source": result.rule.source,
                        "reference_version": result.rule.source_version,
                        "effective_from": result.rule.effective_from.isoformat(),
                        "notes": result.rule.notes,
                        "window_started_at": result.started_at.isoformat(),
                        "window_ended_at": result.ended_at.isoformat(),
                        "averaging_minutes": result.rule.averaging_minutes,
                        "aggregate": result.average,
                        "reference_value": result.rule.value,
                        "reference_unit": result.rule.unit,
                        "aggregate_unit": result.observations[0].unit if result.observations else None,
                        "valid_samples": len(result.observations),
                        "expected_samples": result.expected,
                        "completeness": result.completeness,
                        "window_complete": result.complete,
                        "exceeded": result.exceeded,
                        "limitation": result.limitation,
                    },
                )
            )
        if sustained:
            evidence.append(
                SupportingEvidence(
                    evidence_id=f"sustained:{request.station_id}:{request.pollutant}",
                    source_id=request.station_id,
                    evidence_type="sustained_condition",
                    summary="Configured persistence condition was met; it is an EcoGuard engineering rule.",
                    attributes={
                        "strongly_increasing": increasing,
                        "threshold": self.config.sustained_value_threshold,
                        "unit": self.config.sustained_unit,
                        "minimum_samples": self.config.minimum_consecutive_observations,
                        "minimum_persistence_minutes": self.config.minimum_persistence_minutes,
                        "strong_increase_fraction": self.config.strong_increase_fraction,
                    },
                )
            )
        if baseline["median"] is not None:
            evidence.append(
                SupportingEvidence(
                    evidence_id=f"baseline:{request.station_id}:{request.pollutant}",
                    source_id=request.historical_baseline.source,
                    evidence_type="historical_baseline",
                    summary="Current value was compared with a supplied robust median/MAD baseline.",
                    attributes={
                        "median": baseline["median"],
                        "mad": baseline["mad"],
                        "deviation": baseline["deviation"],
                        "anomalous": baseline["anomalous"],
                        "sufficient": baseline["sufficient"],
                        "unit": request.historical_baseline.unit,
                        "sample_count": len(request.historical_baseline.values),
                        "mad_multiplier": request.historical_baseline.mad_multiplier,
                        "source_version": request.historical_baseline.version,
                        "history_ended_at": request.historical_baseline.ended_at.isoformat(),
                    },
                )
            )
        for item in request.observations:
            evidence.append(SupportingEvidence(
                evidence_id=f"observation:{item.provider_channel_id}:{item.observed_at.isoformat()}",
                source_id=item.provider,
                evidence_type="observation_provenance",
                summary="Supplied observation provenance; unusable readings are excluded from assessment.",
                observed_at=item.observed_at,
                attributes={
                    "station_id": item.provider_station_id,
                    "channel_id": item.provider_channel_id,
                    "value": item.value,
                    "unit": item.unit,
                    "provider_unit": item.provider_unit,
                    "provider_timestamp": item.provider_timestamp,
                    "provider_status": item.provider_status,
                    "provider_status_id": item.provider_status_id,
                    "quality_control": item.quality_control,
                    "valid": item.valid,
                },
            ))
        evidence.append(SupportingEvidence(
            evidence_id="detector-policy:v1",
            source_id="ecoguard-air-pollution-detector:v1",
            evidence_type="detector_policy",
            summary="Versioned engineering policy; confidence is not a calibrated probability or health-risk score.",
            attributes=self.config.model_dump(mode="json"),
        ))
        return evidence
