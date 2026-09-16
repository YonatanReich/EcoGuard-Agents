"""Small, deterministic flood rules for gauges, natural cells and cities."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping


HYDROMETRIC_SOURCE = "water_authority_hydrometric_observations"
RAIN_GAUGE_SOURCE = "water_authority_rainfall_observations"
RADAR_SOURCE = "ims_radar_ppi"
FLOOD_SOURCES = (HYDROMETRIC_SOURCE, RAIN_GAUGE_SOURCE, RADAR_SOURCE)


@dataclass(frozen=True)
class FloodPolicy:
    lookback: timedelta = timedelta(hours=30)
    minimum_baseline_samples: int = 300
    minimum_baseline_distinct_days: int = 10
    minimum_baseline_history_days: int = 330
    required_baseline_months: int = 12
    urban_built_up_fraction: float = 0.35
    urban_rain_10m_mm: float = 8.0
    urban_rain_1h_mm: float = 20.0
    urban_rain_6h_mm: float = 45.0
    natural_rain_1h_mm: float = 15.0
    natural_rain_6h_mm: float = 35.0
    natural_rain_24h_mm: float = 55.0
    saturated_antecedent_24h_mm: float = 25.0
    resolution_threshold_ratio: float = 0.8
    resolution_consecutive_samples: int = 2


@dataclass(frozen=True)
class FloodCandidate:
    event_key: str
    candidate_key: str
    cell_id: str
    observed_at: datetime
    latitude: float
    longitude: float
    confidence: float
    severity_hint: str
    location_uncertainty_m: float
    trigger: str
    evidence: dict[str, Any]

    def public(self) -> dict[str, Any]:
        """Return the intentionally small downstream detector contract."""
        return {
            "candidate_key": self.candidate_key,
            "event_type": "flood",
            "cell_id": self.cell_id,
            "observed_at": self.observed_at,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "confidence": self.confidence,
            "severity_hint": self.severity_hint,
            "location_uncertainty_m": self.location_uncertainty_m,
        }


@dataclass(frozen=True)
class FloodResolution:
    """A stable transition that closes one previously emitted candidate."""

    event_key: str
    candidate_key: str
    cell_id: str
    observed_at: datetime
    reason: str
    evidence: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "candidate_key": self.candidate_key,
            "event_type": "flood",
            "cell_id": self.cell_id,
            "observed_at": self.observed_at,
            "status": "resolved",
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RainMetrics:
    rainfall_10m_mm: float
    rainfall_1h_mm: float
    rainfall_6h_mm: float
    rainfall_24h_mm: float
    max_rate_mm_h: float
    has_gauge: bool
    has_radar: bool


def _station_series(
    observations: Iterable[Mapping[str, Any]], source: str, field: str
) -> dict[int, list[tuple[datetime, float]]]:
    series: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for observation in observations:
        if observation["source"] != source:
            continue
        for station in (observation.get("payload") or {}).get("stations", []):
            value = station.get(field)
            if value is not None:
                series[int(station["source_station_id"])].append(
                    (observation["observed_at"], float(value))
                )
    for values in series.values():
        values.sort(key=lambda item: item[0])
    return series


def _maximum_station_total(
    series: Mapping[int, list[tuple[datetime, float]]],
    as_of: datetime,
    period: timedelta,
) -> float:
    return max(
        (
            sum(value for at, value in values if as_of - period < at <= as_of)
            for values in series.values()
        ),
        default=0.0,
    )


def _radar_total(
    observations: Iterable[Mapping[str, Any]], as_of: datetime, period: timedelta
) -> float:
    return sum(
        float((observation.get("payload") or {}).get("rainfall_mm", 0.0))
        for observation in observations
        if observation["source"] == RADAR_SOURCE
        and as_of - period < observation["observed_at"] <= as_of
    )


def rain_metrics(
    observations: list[Mapping[str, Any]], as_of: datetime
) -> RainMetrics:
    """Combine gauges and radar without adding two estimates of the same rain."""
    gauge_series = _station_series(observations, RAIN_GAUGE_SOURCE, "rainfall_mm")
    periods = (
        timedelta(minutes=10),
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(hours=24),
    )
    totals = []
    for period in periods:
        gauge = _maximum_station_total(gauge_series, as_of, period)
        radar = _radar_total(observations, as_of, period)
        # These sources estimate the same rainfall. Taking the larger estimate
        # is conservative while avoiding the double-counting caused by a sum.
        totals.append(max(gauge, radar))

    radar_rates = [
        float((item.get("payload") or {}).get("rain_rate_max_mm_h", 0.0))
        for item in observations
        if item["source"] == RADAR_SOURCE
        and as_of - timedelta(minutes=10) < item["observed_at"] <= as_of
    ]
    gauge_rate = _maximum_station_total(
        gauge_series, as_of, timedelta(minutes=10)
    ) * 6.0
    return RainMetrics(
        rainfall_10m_mm=totals[0],
        rainfall_1h_mm=totals[1],
        rainfall_6h_mm=totals[2],
        rainfall_24h_mm=totals[3],
        max_rate_mm_h=max([gauge_rate, *radar_rates], default=0.0),
        has_gauge=any(
            at <= as_of for values in gauge_series.values() for at, _ in values
        ),
        has_radar=any(
            item["source"] == RADAR_SOURCE and item["observed_at"] <= as_of
            for item in observations
        ),
    )


def _rain_times(observations: Iterable[Mapping[str, Any]]) -> list[datetime]:
    return sorted(
        {
            item["observed_at"]
            for item in observations
            if item["source"] in (RAIN_GAUGE_SOURCE, RADAR_SOURCE)
        }
    )


def _rain_trigger(
    metrics: RainMetrics, thresholds: tuple[tuple[str, float], ...]
) -> tuple[str, float] | None:
    for field, threshold in thresholds:
        value = float(getattr(metrics, field))
        if value >= threshold:
            return field, value / threshold
    return None


def _rain_confidence(metrics: RainMetrics, *, urban: bool) -> float:
    confidence = 0.66 if urban else 0.63
    if metrics.has_gauge:
        confidence += 0.07
    if metrics.has_radar:
        confidence += 0.05
    if metrics.has_gauge and metrics.has_radar:
        confidence += 0.05
    return min(confidence, 0.86)


def _severity(ratio: float) -> str:
    if ratio >= 2.0:
        return "critical"
    if ratio >= 1.5:
        return "high"
    return "moderate"


def _gauge_severity(station: Mapping[str, Any], discharge: float, ratio: float) -> str:
    for period, severity in ((20, "critical"), (10, "high"), (2, "moderate")):
        threshold = station.get(f"flow_threshold_{period}y_m3s")
        if threshold is not None and discharge >= float(threshold):
            return severity
    return _severity(ratio)


def _baseline_value(
    baseline: Mapping[str, Any],
    *,
    value_field: str,
    sample_count_field: str,
    distinct_days_field: str,
    policy: FloodPolicy,
) -> float | None:
    """Return a baseline only when annual and per-metric coverage is adequate."""
    if (
        int(baseline.get("covered_months") or 0) < policy.required_baseline_months
        or int(baseline.get("history_span_days") or 0)
        < policy.minimum_baseline_history_days
        or int(baseline.get(sample_count_field) or 0)
        < policy.minimum_baseline_samples
        or int(baseline.get(distinct_days_field) or 0)
        < policy.minimum_baseline_distinct_days
    ):
        return None
    value = baseline.get(value_field)
    return float(value) if value is not None else None


def _gauge_candidates(
    cell_id: str,
    observations: list[Mapping[str, Any]],
    baselines: Mapping[tuple[int, int], Mapping[str, Any]],
    policy: FloodPolicy,
    rain: RainMetrics | None,
) -> list[FloodCandidate]:
    by_station: dict[int, list[tuple[datetime, Mapping[str, Any]]]] = defaultdict(list)
    for observation in observations:
        if observation["source"] != HYDROMETRIC_SOURCE:
            continue
        for station in (observation.get("payload") or {}).get("stations", []):
            by_station[int(station["source_station_id"])].append(
                (observation["observed_at"], station)
            )

    candidates: list[FloodCandidate] = []
    for station_id, samples in by_station.items():
        samples.sort(key=lambda item: item[0])
        # Search backward for the latest crossing. This still emits when the
        # worker receives several readings at once and the newest two are both
        # above threshold. The deterministic key makes an older crossing a
        # harmless no-op if it was already emitted on a previous run.
        for index in range(len(samples) - 1, -1, -1):
            observed_at, current = samples[index]
            previous = samples[index - 1][1] if index > 0 else {}
            baseline = baselines.get((station_id, observed_at.month), {})

            discharge = current.get("discharge_m3s")
            previous_discharge = previous.get("discharge_m3s")
            q2 = current.get("flow_threshold_2y_m3s")
            baseline_discharge = _baseline_value(
                baseline,
                value_field="discharge_p95_m3s",
                sample_count_field="discharge_sample_count",
                distinct_days_field="discharge_distinct_days",
                policy=policy,
            )
            discharge_thresholds = [
                ("rating_curve", float(q2))
                for _ in [0]
                if q2 is not None and float(q2) > 0
            ]
            if baseline_discharge is not None and float(baseline_discharge) > 0:
                discharge_thresholds.append(
                    ("seasonal_baseline", float(baseline_discharge))
                )

            trigger: str | None = None
            threshold = 0.0
            ratio = 0.0
            if discharge is not None:
                for name, candidate_threshold in discharge_thresholds:
                    if float(discharge) >= candidate_threshold and (
                        (previous_discharge is None and len(samples) == 1)
                        or (
                            previous_discharge is not None
                            and float(previous_discharge) < candidate_threshold
                        )
                    ):
                        trigger = f"gauge_discharge_{name}"
                        threshold = candidate_threshold
                        ratio = float(discharge) / candidate_threshold
                        break

            stage = current.get("water_height_m")
            previous_stage = previous.get("water_height_m")
            baseline_stage = _baseline_value(
                baseline,
                value_field="stage_p95_m",
                sample_count_field="stage_sample_count",
                distinct_days_field="stage_distinct_days",
                policy=policy,
            )
            if (
                trigger is None
                and stage is not None
                and baseline_stage is not None
                and float(stage) >= float(baseline_stage)
                and (
                    (previous_stage is None and len(samples) == 1)
                    or (
                        previous_stage is not None
                        and float(previous_stage) < float(baseline_stage)
                    )
                )
            ):
                trigger = "gauge_stage_seasonal_baseline"
                threshold = float(baseline_stage)
                denominator = max(abs(threshold), 0.1)
                ratio = 1.0 + max(0.0, float(stage) - threshold) / denominator

            if trigger is None:
                continue

            confidence = 0.88 if "rating_curve" in trigger else 0.76
            if rain and (rain.rainfall_1h_mm >= 5 or rain.rainfall_6h_mm >= 15):
                confidence += 0.07
            severity = (
                _gauge_severity(current, float(discharge), ratio)
                if discharge is not None
                else _severity(ratio)
            )
            candidates.append(
                FloodCandidate(
                    event_key=f"flood:gauge:{cell_id}:{station_id}",
                    candidate_key=(
                        f"flood:{trigger}:{cell_id}:{station_id}:"
                        f"{observed_at.isoformat()}"
                    ),
                    cell_id=cell_id,
                    observed_at=observed_at,
                    latitude=float(current["latitude"]),
                    longitude=float(current["longitude"]),
                    confidence=min(confidence, 0.97),
                    severity_hint=severity,
                    location_uncertainty_m=100.0,
                    trigger=trigger,
                    evidence={
                        "source_station_id": station_id,
                        "value": discharge if discharge is not None else stage,
                        "threshold": threshold,
                        "rainfall_1h_mm": rain.rainfall_1h_mm if rain else None,
                        "rainfall_6h_mm": rain.rainfall_6h_mm if rain else None,
                    },
                )
            )
            break
    return candidates


def _rain_thresholds(
    context: Mapping[str, Any],
    metrics: RainMetrics,
    policy: FloodPolicy,
) -> tuple[bool, tuple[tuple[str, float], ...]]:
    """Return the opening thresholds for the cell's urban/natural regime."""
    built_up = float(context.get("built_up_fraction") or 0.0)
    urban = built_up >= policy.urban_built_up_fraction
    if urban:
        return urban, (
            ("rainfall_10m_mm", policy.urban_rain_10m_mm),
            ("rainfall_1h_mm", policy.urban_rain_1h_mm),
            ("rainfall_6h_mm", policy.urban_rain_6h_mm),
        )

    # Steep terrain moves water into wadis faster. Antecedent rain is a simple
    # soil-saturation proxy until a soil product is collected.
    slope = float(context.get("slope_deg") or 0.0)
    terrain_factor = 0.85 if slope >= 8 else (0.95 if slope >= 3 else 1.0)
    saturation_factor = (
        0.85
        if (
            metrics.rainfall_24h_mm - metrics.rainfall_1h_mm
            >= policy.saturated_antecedent_24h_mm
        )
        else 1.0
    )
    factor = terrain_factor * saturation_factor
    return urban, (
        ("rainfall_1h_mm", policy.natural_rain_1h_mm * factor),
        ("rainfall_6h_mm", policy.natural_rain_6h_mm * factor),
        ("rainfall_24h_mm", policy.natural_rain_24h_mm * terrain_factor),
    )


def _rain_candidate(
    cell_id: str,
    observations: list[Mapping[str, Any]],
    context: Mapping[str, Any] | None,
    policy: FloodPolicy,
) -> FloodCandidate | None:
    times = _rain_times(observations)
    if not times or context is None:
        return None
    built_up = float(context.get("built_up_fraction") or 0.0)
    urban = built_up >= policy.urban_built_up_fraction
    if not urban and context.get("drainage_basin_id") is None and (
        context.get("distance_to_stream_m") is None
        or float(context["distance_to_stream_m"]) > 5000
    ):
        return None

    crossing: tuple[str, float] | None = None
    current: RainMetrics | None = None
    as_of = times[-1]
    for index in range(len(times) - 1, -1, -1):
        as_of = times[index]
        current = rain_metrics(observations, as_of)
        previous = (
            rain_metrics(observations, times[index - 1])
            if index > 0
            else (
                RainMetrics(0.0, 0.0, 0.0, 0.0, 0.0, False, False)
                if len(times) == 1
                else current
            )
        )
        urban, thresholds = _rain_thresholds(context, current, policy)
        trigger_prefix = "urban_rain" if urban else "natural_rain"

        crossing = _rain_trigger(current, thresholds)
        if crossing is not None and _rain_trigger(previous, thresholds) is None:
            break
        crossing = None

    if crossing is None or current is None:
        return None
    field, ratio = crossing
    threshold = float(getattr(current, field)) / ratio
    latitude = float(context["latitude"])
    longitude = float(context["longitude"])
    trigger = f"{trigger_prefix}_{field.removeprefix('rainfall_').removesuffix('_mm')}"
    return FloodCandidate(
        event_key=f"flood:rain:{cell_id}",
        candidate_key=f"flood:{trigger}:{cell_id}:{as_of.isoformat()}",
        cell_id=cell_id,
        observed_at=as_of,
        latitude=latitude,
        longitude=longitude,
        confidence=_rain_confidence(current, urban=urban),
        severity_hint=_severity(ratio),
        location_uncertainty_m=2500.0,
        trigger=trigger,
        evidence={
            "rainfall_10m_mm": current.rainfall_10m_mm,
            "rainfall_1h_mm": current.rainfall_1h_mm,
            "rainfall_6h_mm": current.rainfall_6h_mm,
            "rainfall_24h_mm": current.rainfall_24h_mm,
            "max_rate_mm_h": current.max_rate_mm_h,
            "built_up_fraction": built_up,
            "metric": field,
            "threshold": threshold,
        },
    )


def _gauge_resolution(
    event: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    policy: FloodPolicy,
) -> FloodResolution | None:
    evidence = event.get("evidence") or {}
    station_id = evidence.get("source_station_id")
    threshold = evidence.get("threshold")
    if station_id is None or threshold is None:
        return None

    field = (
        "discharge_m3s"
        if "gauge_discharge" in str(event["trigger"])
        else "water_height_m"
    )
    samples: list[tuple[datetime, float]] = []
    for observation in observations:
        if (
            observation["source"] != HYDROMETRIC_SOURCE
            or observation["observed_at"] <= event["opened_at"]
        ):
            continue
        for station in (observation.get("payload") or {}).get("stations", []):
            value = station.get(field)
            if int(station["source_station_id"]) == int(station_id) and value is not None:
                samples.append((observation["observed_at"], float(value)))

    samples.sort(key=lambda item: item[0])
    required = policy.resolution_consecutive_samples
    if len(samples) < required:
        return None
    recent = samples[-required:]
    exit_threshold = float(threshold) * policy.resolution_threshold_ratio
    if not all(value < exit_threshold for _, value in recent):
        return None
    return FloodResolution(
        event_key=str(event["event_key"]),
        candidate_key=str(event["candidate_key"]),
        cell_id=str(event["cell_id"]),
        observed_at=recent[-1][0],
        reason="gauge_below_exit_threshold",
        evidence={
            "metric": field,
            "exit_threshold": exit_threshold,
            "recent_values": [value for _, value in recent],
        },
    )


def _rain_resolution(
    event: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    context: Mapping[str, Any] | None,
    policy: FloodPolicy,
) -> FloodResolution | None:
    if context is None:
        return None
    times = [
        observed_at
        for observed_at in _rain_times(observations)
        if observed_at > event["opened_at"]
    ]
    required = policy.resolution_consecutive_samples
    if len(times) < required:
        return None

    recent = times[-required:]
    recent_metrics: list[RainMetrics] = []
    for observed_at in recent:
        metrics = rain_metrics(observations, observed_at)
        _, opening_thresholds = _rain_thresholds(context, metrics, policy)
        exit_thresholds = tuple(
            (field, threshold * policy.resolution_threshold_ratio)
            for field, threshold in opening_thresholds
        )
        if _rain_trigger(metrics, exit_thresholds) is not None:
            return None
        recent_metrics.append(metrics)

    latest = recent_metrics[-1]
    return FloodResolution(
        event_key=str(event["event_key"]),
        candidate_key=str(event["candidate_key"]),
        cell_id=str(event["cell_id"]),
        observed_at=recent[-1],
        reason="rain_below_exit_threshold",
        evidence={
            "rainfall_10m_mm": latest.rainfall_10m_mm,
            "rainfall_1h_mm": latest.rainfall_1h_mm,
            "rainfall_6h_mm": latest.rainfall_6h_mm,
            "rainfall_24h_mm": latest.rainfall_24h_mm,
        },
    )


def evaluate_resolutions(
    observations: list[Mapping[str, Any]],
    context: Mapping[str, Any] | None,
    active_events: Iterable[Mapping[str, Any]],
    policy: FloodPolicy | None = None,
) -> list[FloodResolution]:
    """Resolve active events only after fresh, consistently low readings."""
    selected_policy = policy or FloodPolicy()
    resolutions: list[FloodResolution] = []
    for event in active_events:
        if str(event["trigger"]).startswith("gauge_"):
            resolution = _gauge_resolution(event, observations, selected_policy)
        else:
            resolution = _rain_resolution(
                event, observations, context, selected_policy
            )
        if resolution is not None:
            resolutions.append(resolution)
    return resolutions


def evaluate_cell(
    cell_id: str,
    observations: list[Mapping[str, Any]],
    context: Mapping[str, Any] | None,
    baselines: Mapping[tuple[int, int], Mapping[str, Any]],
    policy: FloodPolicy | None = None,
) -> list[FloodCandidate]:
    """Evaluate one cell using threshold crossings; no classifier is involved."""
    selected_policy = policy or FloodPolicy()
    rain_times = _rain_times(observations)
    rain = rain_metrics(observations, rain_times[-1]) if rain_times else None
    candidates = _gauge_candidates(
        cell_id, observations, baselines, selected_policy, rain
    )
    rain_candidate = _rain_candidate(cell_id, observations, context, selected_policy)
    if rain_candidate is not None:
        candidates.append(rain_candidate)
    return candidates
