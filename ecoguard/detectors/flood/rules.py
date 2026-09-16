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
    maximum_ingestion_lag: timedelta = timedelta(hours=2)
    maximum_future_skew: timedelta = timedelta(minutes=15)
    minimum_radar_valid_fraction: float = 0.5
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
    observations: Iterable[Mapping[str, Any]],
    as_of: datetime,
    period: timedelta,
    policy: FloodPolicy,
    *,
    spatial_average: bool,
) -> float:
    by_frame: dict[datetime, list[float]] = defaultdict(list)
    frame_cell_counts: dict[datetime, int] = {}
    for observation in observations:
        if (
            observation["source"] != RADAR_SOURCE
            or not _usable_radar(observation, policy)
            or not as_of - period < observation["observed_at"] <= as_of
        ):
            continue
        by_frame[observation["observed_at"]].append(
            float((observation.get("payload") or {}).get("rainfall_mm", 0.0))
        )
        declared_count = int(observation.get("spatial_cell_count") or 0)
        if declared_count > 0:
            frame_cell_counts[observation["observed_at"]] = max(
                frame_cell_counts.get(observation["observed_at"], 0),
                declared_count,
            )
    if spatial_average:
        return sum(
            sum(values) / max(frame_cell_counts.get(at, 0), len(values))
            for at, values in by_frame.items()
        )
    return sum(value for values in by_frame.values() for value in values)


def _usable_radar(
    observation: Mapping[str, Any], policy: FloodPolicy
) -> bool:
    payload = observation.get("payload") or {}
    coverage = payload.get("valid_pixel_fraction")
    return coverage is not None and float(coverage) >= policy.minimum_radar_valid_fraction


def rain_metrics(
    observations: list[Mapping[str, Any]],
    as_of: datetime,
    policy: FloodPolicy | None = None,
    *,
    spatial_average: bool = False,
) -> RainMetrics:
    """Combine gauges and radar without adding two estimates of the same rain."""
    selected_policy = policy or FloodPolicy()
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
        radar = _radar_total(
            observations,
            as_of,
            period,
            selected_policy,
            spatial_average=spatial_average,
        )
        # These sources estimate the same rainfall. Taking the larger estimate
        # is conservative while avoiding the double-counting caused by a sum.
        totals.append(max(gauge, radar))

    radar_rates = [
        float((item.get("payload") or {}).get("rain_rate_max_mm_h", 0.0))
        for item in observations
        if item["source"] == RADAR_SOURCE
        and _usable_radar(item, selected_policy)
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
            item["source"] == RADAR_SOURCE
            and _usable_radar(item, selected_policy)
            and item["observed_at"] <= as_of
            for item in observations
        ),
    )


def _rain_times(
    observations: Iterable[Mapping[str, Any]], policy: FloodPolicy
) -> list[datetime]:
    return sorted(
        {
            item["observed_at"]
            for item in observations
            if item["source"] == RAIN_GAUGE_SOURCE
            or (item["source"] == RADAR_SOURCE and _usable_radar(item, policy))
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


def _rain_confidence(
    metrics: RainMetrics,
    *,
    urban: bool,
    catchment_support: bool = False,
) -> float:
    confidence = 0.66 if urban else 0.63
    if metrics.has_gauge:
        confidence += 0.07
    if metrics.has_radar:
        confidence += 0.05
    if metrics.has_gauge and metrics.has_radar:
        confidence += 0.05
    if catchment_support:
        confidence += 0.05
    return min(confidence, 0.91)


def _severity(ratio: float) -> str:
    if ratio >= 2.0:
        return "critical"
    if ratio >= 1.5:
        return "high"
    return "moderate"


def _exceeded_return_period(
    station: Mapping[str, Any], discharge: float
) -> int | None:
    for period in (100, 50, 20, 10, 5, 2):
        threshold = station.get(f"flow_threshold_{period}y_m3s")
        if threshold is not None and discharge >= float(threshold):
            return period
    return None


def _gauge_severity(return_period: int | None, ratio: float) -> str:
    if return_period is None:
        return _severity(ratio)
    if return_period >= 20:
        return "critical"
    if return_period >= 10:
        return "high"
    return "moderate"


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
            baseline_discharge = _baseline_value(
                baseline,
                value_field="discharge_p95_m3s",
                sample_count_field="discharge_sample_count",
                distinct_days_field="discharge_distinct_days",
                policy=policy,
            )
            official_thresholds = [
                (period, float(current[f"flow_threshold_{period}y_m3s"]))
                for period in (2, 5, 10, 20, 50, 100)
                if current.get(f"flow_threshold_{period}y_m3s") is not None
                and float(current[f"flow_threshold_{period}y_m3s"]) > 0
            ]
            discharge_thresholds = [
                ("rating_curve", threshold, period)
                for period, threshold in official_thresholds[:1]
            ]
            if baseline_discharge is not None and float(baseline_discharge) > 0:
                discharge_thresholds.append(
                    ("seasonal_baseline", float(baseline_discharge), None)
                )

            trigger: str | None = None
            threshold = 0.0
            ratio = 0.0
            opening_return_period: int | None = None
            if discharge is not None:
                for name, candidate_threshold, return_period in discharge_thresholds:
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
                        opening_return_period = return_period
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
            exceeded_return_period = (
                _exceeded_return_period(current, float(discharge))
                if discharge is not None
                else None
            )
            severity = _gauge_severity(exceeded_return_period, ratio)
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
                        "opening_return_period_years": opening_return_period,
                        "exceeded_return_period_years": exceeded_return_period,
                        "rainfall_1h_mm": rain.rainfall_1h_mm if rain else None,
                        "rainfall_6h_mm": rain.rainfall_6h_mm if rain else None,
                    },
                )
            )
            break
    return candidates


def _urban_classification(
    context: Mapping[str, Any], policy: FloodPolicy
) -> bool | None:
    """Return a cached urban classification without guessing missing data."""
    status = context.get("urban_classification_status")
    if status is not None:
        if status != "classified" or context.get("is_urban") is None:
            return None
        return bool(context["is_urban"])
    if context.get("is_urban") is not None:
        return bool(context["is_urban"])
    built_up = context.get("built_up_fraction")
    if built_up is None:
        return None
    return float(built_up) >= policy.urban_built_up_fraction


def _rain_thresholds(
    context: Mapping[str, Any],
    metrics: RainMetrics,
    policy: FloodPolicy,
) -> tuple[bool | None, tuple[tuple[str, float], ...]]:
    """Return the opening thresholds for the cell's urban/natural regime."""
    urban = _urban_classification(context, policy)
    if urban is None:
        return None, ()
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


def _catchment_support(metrics: RainMetrics | None, policy: FloodPolicy) -> bool:
    """Use basin-average rain as corroboration, never as a sole trigger."""
    if metrics is None:
        return False
    return (
        metrics.rainfall_1h_mm >= policy.natural_rain_1h_mm * 0.6
        or metrics.rainfall_6h_mm >= policy.natural_rain_6h_mm * 0.6
        or metrics.rainfall_24h_mm >= policy.natural_rain_24h_mm * 0.6
    )


def _rain_candidate(
    cell_id: str,
    observations: list[Mapping[str, Any]],
    context: Mapping[str, Any] | None,
    policy: FloodPolicy,
    catchment_observations: list[Mapping[str, Any]],
) -> FloodCandidate | None:
    times = _rain_times(observations, policy)
    if not times or context is None:
        return None
    urban = _urban_classification(context, policy)
    if urban is None:
        return None
    if not urban and context.get("drainage_basin_id") is None and (
        context.get("distance_to_stream_m") is None
        or float(context["distance_to_stream_m"]) > 5000
    ):
        return None

    crossing: tuple[str, float] | None = None
    current: RainMetrics | None = None
    catchment: RainMetrics | None = None
    as_of = times[-1]
    for index in range(len(times) - 1, -1, -1):
        as_of = times[index]
        current = rain_metrics(observations, as_of, policy)
        catchment = (
            rain_metrics(
                catchment_observations,
                as_of,
                policy,
                spatial_average=True,
            )
            if catchment_observations
            else None
        )
        previous = (
            rain_metrics(observations, times[index - 1], policy)
            if index > 0
            else (
                RainMetrics(0.0, 0.0, 0.0, 0.0, 0.0, False, False)
                if len(times) == 1
                else current
            )
        )
        _, thresholds = _rain_thresholds(context, current, policy)
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
        confidence=_rain_confidence(
            current,
            urban=urban,
            catchment_support=(not urban and _catchment_support(catchment, policy)),
        ),
        severity_hint=_severity(ratio),
        location_uncertainty_m=2500.0,
        trigger=trigger,
        evidence={
            "rainfall_10m_mm": current.rainfall_10m_mm,
            "rainfall_1h_mm": current.rainfall_1h_mm,
            "rainfall_6h_mm": current.rainfall_6h_mm,
            "rainfall_24h_mm": current.rainfall_24h_mm,
            "max_rate_mm_h": current.max_rate_mm_h,
            "built_up_fraction": context.get("built_up_fraction"),
            "urban_classification_status": context.get(
                "urban_classification_status", "legacy_fraction"
            ),
            "catchment_rainfall_1h_mm": (
                catchment.rainfall_1h_mm if catchment else None
            ),
            "catchment_rainfall_6h_mm": (
                catchment.rainfall_6h_mm if catchment else None
            ),
            "catchment_rainfall_24h_mm": (
                catchment.rainfall_24h_mm if catchment else None
            ),
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
    catchment_observations: list[Mapping[str, Any]],
) -> FloodResolution | None:
    if context is None:
        return None
    times = [
        observed_at
        for observed_at in _rain_times(observations, policy)
        if observed_at > event["opened_at"]
    ]
    required = policy.resolution_consecutive_samples
    if len(times) < required:
        return None

    recent = times[-required:]
    recent_metrics: list[RainMetrics] = []
    for observed_at in recent:
        metrics = rain_metrics(observations, observed_at, policy)
        urban, opening_thresholds = _rain_thresholds(context, metrics, policy)
        if urban is None:
            return None
        if not urban and catchment_observations:
            catchment = rain_metrics(
                catchment_observations,
                observed_at,
                policy,
                spatial_average=True,
            )
            if _catchment_support(catchment, policy):
                return None
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
    catchment_observations: list[Mapping[str, Any]] | None = None,
) -> list[FloodResolution]:
    """Resolve active events only after fresh, consistently low readings."""
    selected_policy = policy or FloodPolicy()
    resolutions: list[FloodResolution] = []
    for event in active_events:
        if str(event["trigger"]).startswith("gauge_"):
            resolution = _gauge_resolution(event, observations, selected_policy)
        else:
            resolution = _rain_resolution(
                event,
                observations,
                context,
                selected_policy,
                catchment_observations or [],
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
    catchment_observations: list[Mapping[str, Any]] | None = None,
) -> list[FloodCandidate]:
    """Evaluate one cell using threshold crossings; no classifier is involved."""
    selected_policy = policy or FloodPolicy()
    rain_times = _rain_times(observations, selected_policy)
    rain = (
        rain_metrics(observations, rain_times[-1], selected_policy)
        if rain_times
        else None
    )
    candidates = _gauge_candidates(
        cell_id, observations, baselines, selected_policy, rain
    )
    rain_candidate = _rain_candidate(
        cell_id,
        observations,
        context,
        selected_policy,
        catchment_observations or [],
    )
    if rain_candidate is not None:
        candidates.append(rain_candidate)
    return candidates
