"""Detect hydrological flood signals from data cached in PostgreSQL.

Collectors and detection are deliberately separate. The detector never fetches
provider data; it evaluates a recent, de-duplicated observation history already
stored by the collectors.

The Water Authority return-period discharges remain the authoritative measure
of flow rarity. They are combined with persistence and rate-of-rise evidence
to decide whether a flood wave is developing. This distinction lets stations
without return-period thresholds still contribute a hydrological detection,
without pretending that their flow intensity can be ranked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any, Protocol
import unicodedata


# Provider thresholds describe discharges expected once every N years.
RETURN_PERIODS = (2, 5, 10, 20, 50, 100)
# Several windows show both immediate and sustained hydrological change.
TREND_WINDOWS_MINUTES = (10, 30, 60)
HYDROMETRIC_COLLECTOR_SOURCE = (
    "water_authority_hydrometric_observations"
)
RAINFALL_COLLECTOR_SOURCE = "water_authority_rainfall_observations"
HYDROLOGY_COLLECTOR_SOURCES = (
    HYDROMETRIC_COLLECTOR_SOURCE,
    RAINFALL_COLLECTOR_SOURCE,
)


class StationHistoryRepository(Protocol):
    """Cached data access required by the detector."""

    def load_station_histories(
        self,
        *,
        observed_since: datetime,
        rainfall_since: datetime,
        as_of: datetime,
        stream_candidate_radius_m: float,
        stream_candidate_limit: int,
    ) -> list[dict[str, Any]]: ...

    def load_stream_network(self) -> dict[int, dict[str, Any]]: ...

    def load_latest_collector_runs(
        self, *, sources: tuple[str, ...]
    ) -> dict[str, dict[str, Any]]: ...


@dataclass(frozen=True)
class FloodDetectionPolicy:
    """Configurable operational heuristics around provider-owned thresholds.

    ``rapid_stage_rise_m_per_hour`` is a provisional supporting trigger, not a
    Water Authority flood threshold. Keeping it in policy makes that limitation
    explicit and allows calibration when historical labelled events exist.
    """

    # Freshness limits prevent old readings from looking like current floods.
    max_observation_age: timedelta = timedelta(minutes=30)
    history_window: timedelta = timedelta(minutes=90)
    rainfall_history_window: timedelta = timedelta(hours=24)
    max_rainfall_age: timedelta = timedelta(minutes=30)
    # A rapid rise must persist across observations to reject one-point spikes.
    minimum_consecutive_rises: int = 2
    threshold_persistence_observations: int = 2
    rapid_stage_rise_m_per_hour: float = 0.25
    rapid_discharge_rise_q2_per_hour: float = 0.25
    # Stream matching is intentionally conservative because it drives routing.
    stream_candidate_radius_m: float = 2_000.0
    stream_candidate_limit: int = 20
    strong_stream_distance_m: float = 100.0
    max_reliable_stream_distance_m: float = 1_000.0
    stream_ambiguity_distance_m: float = 50.0
    stream_name_override_distance_factor: float = 3.0
    max_downstream_hops: int = 20

    def __post_init__(self) -> None:
        if self.max_observation_age <= timedelta(0):
            raise ValueError("max_observation_age must be positive")
        if self.history_window <= self.max_observation_age:
            raise ValueError(
                "history_window must be longer than max_observation_age"
            )
        if self.rainfall_history_window <= timedelta(0):
            raise ValueError("rainfall_history_window must be positive")
        if self.max_rainfall_age <= timedelta(0):
            raise ValueError("max_rainfall_age must be positive")
        if self.minimum_consecutive_rises < 1:
            raise ValueError("minimum_consecutive_rises must be positive")
        if self.threshold_persistence_observations < 2:
            raise ValueError(
                "threshold_persistence_observations must be at least two"
            )
        if self.rapid_stage_rise_m_per_hour <= 0:
            raise ValueError("rapid_stage_rise_m_per_hour must be positive")
        if self.rapid_discharge_rise_q2_per_hour <= 0:
            raise ValueError(
                "rapid_discharge_rise_q2_per_hour must be positive"
            )
        if self.stream_candidate_radius_m <= 0:
            raise ValueError("stream_candidate_radius_m must be positive")
        if self.stream_candidate_limit < 2:
            raise ValueError("stream_candidate_limit must be at least two")
        if self.strong_stream_distance_m <= 0:
            raise ValueError("strong_stream_distance_m must be positive")
        if (
            self.max_reliable_stream_distance_m
            < self.strong_stream_distance_m
        ):
            raise ValueError(
                "max_reliable_stream_distance_m must be at least "
                "strong_stream_distance_m"
            )
        if (
            self.stream_candidate_radius_m
            < self.max_reliable_stream_distance_m
        ):
            raise ValueError(
                "stream_candidate_radius_m must be at least "
                "max_reliable_stream_distance_m"
            )
        if self.stream_ambiguity_distance_m < 0:
            raise ValueError(
                "stream_ambiguity_distance_m cannot be negative"
            )
        if self.stream_name_override_distance_factor < 1:
            raise ValueError(
                "stream_name_override_distance_factor must be at least one"
            )
        if self.max_downstream_hops < 1:
            raise ValueError("max_downstream_hops must be positive")


class FloodDetectionAgent:
    """Scan cached station histories for persistent or rapidly rising flow."""

    def __init__(
        self,
        repository: StationHistoryRepository | None = None,
        policy: FloodDetectionPolicy | None = None,
    ) -> None:
        if repository is None:
            from ecoguard.database.repositories.flood_detection import (
                PostgresFloodDetectionRepository,
            )

            repository = PostgresFloodDetectionRepository()
        self.repository = repository
        self.policy = policy or FloodDetectionPolicy()

    def detect_floods(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return detected events, watches and explicit coverage gaps."""
        checked_at = _utc(now or datetime.now(timezone.utc), "now")
        observed_since = checked_at - self.policy.history_window
        rainfall_since = checked_at - (
            self.policy.rainfall_history_window
            + self.policy.max_rainfall_age
        )
        # Histories arrive pre-enriched with basin, rain and stream candidates.
        try:
            histories = self.repository.load_station_histories(
                observed_since=observed_since,
                rainfall_since=rainfall_since,
                as_of=checked_at,
                stream_candidate_radius_m=(
                    self.policy.stream_candidate_radius_m
                ),
                stream_candidate_limit=self.policy.stream_candidate_limit,
            )
        except Exception as error:
            # A primary-data failure is inconclusive, never "no flood".
            return {
                "metadata": {
                    "timestamp": checked_at.isoformat(),
                    "collection_status": "failed",
                },
                "event_type": "flood",
                "detected": None,
                "detected_events": [],
                "watch_events": [],
                "input_station_count": 0,
                "assessed_station_count": 0,
                "unassessed_stations": [],
                "source_status": {"hydrology_database": "failed"},
                "error": f"{type(error).__name__}: {error}",
            }

        # Collector-run metadata is optional diagnostic context for cache health.
        collector_runs_available = True
        collector_runs_error: str | None = None
        try:
            collector_runs = self.repository.load_latest_collector_runs(
                sources=HYDROLOGY_COLLECTOR_SOURCES
            )
        except Exception as error:
            collector_runs = {}
            collector_runs_available = False
            collector_runs_error = f"{type(error).__name__}: {error}"

        detected_events: list[dict[str, Any]] = []
        watch_events: list[dict[str, Any]] = []
        unassessed_stations: list[dict[str, Any]] = []
        assessed_station_count = 0

        # Keep detected, watch and unassessed outcomes separate for consumers.
        for history in histories:
            outcome = self._evaluate_station(history, checked_at)
            if outcome["status"] == "detected":
                assessed_station_count += 1
                detected_events.append(outcome["event"])
            elif outcome["status"] == "watch":
                assessed_station_count += 1
                watch_events.append(outcome["event"])
            elif outcome["status"] == "clear":
                assessed_station_count += 1
            else:
                unassessed_stations.append(outcome["station"])

        event_outputs = [*detected_events, *watch_events]
        # Load the network only when an event has a reliable origin stream.
        stream_network_required = any(
            event["stream_context"]["matched"]
            for event in event_outputs
        )
        stream_network: dict[int, dict[str, Any]] = {}
        stream_network_status = "not_required"
        stream_network_error: str | None = None
        if stream_network_required:
            try:
                stream_network = self.repository.load_stream_network()
                stream_network_status = "success"
            except Exception as error:
                stream_network_status = "failed"
                stream_network_error = f"{type(error).__name__}: {error}"
        for event in event_outputs:
            event["downstream_route"] = _downstream_route(
                event["stream_context"],
                stream_network,
                max_hops=self.policy.max_downstream_hops,
                network_available=stream_network_status != "failed",
            )

        # Overall detection is tri-state: true, clear false, or unknown.
        if detected_events:
            detected: bool | None = True
        elif not histories or unassessed_stations:
            detected = None
        else:
            detected = False

        # Cache health describes coverage independently of detection outcome.
        hydrometric_cache = _hydrometric_cache_health(
            histories,
            checked_at=checked_at,
            max_age=self.policy.max_observation_age,
        )
        rainfall_cache = _rainfall_cache_health(
            histories,
            checked_at=checked_at,
            max_age=self.policy.max_rainfall_age,
        )
        result = {
            "metadata": {
                "timestamp": checked_at.isoformat(),
                "collection_status": "success",
                "history_window_minutes": int(
                    self.policy.history_window.total_seconds() / 60
                ),
            },
            "event_type": "flood",
            "detected": detected,
            "detected_events": detected_events,
            "watch_events": watch_events,
            "input_station_count": len(histories),
            "assessed_station_count": assessed_station_count,
            "unassessed_stations": unassessed_stations,
            "source_status": {
                "hydrology_database": "success",
                "hydrometric_observations": _collector_source_health(
                    source=HYDROMETRIC_COLLECTOR_SOURCE,
                    latest_run=collector_runs.get(
                        HYDROMETRIC_COLLECTOR_SOURCE
                    ),
                    cache=hydrometric_cache,
                    run_history_available=collector_runs_available,
                ),
                "rainfall_observations": _collector_source_health(
                    source=RAINFALL_COLLECTOR_SOURCE,
                    latest_run=collector_runs.get(
                        RAINFALL_COLLECTOR_SOURCE
                    ),
                    cache=rainfall_cache,
                    run_history_available=collector_runs_available,
                ),
                "stream_network": stream_network_status,
            },
        }
        source_errors = {}
        if collector_runs_error is not None:
            source_errors["collector_runs"] = collector_runs_error
        if stream_network_error is not None:
            source_errors["stream_network"] = stream_network_error
        if source_errors:
            result["source_errors"] = source_errors
        return result

    def _evaluate_station(
        self,
        snapshot: dict[str, Any],
        checked_at: datetime,
    ) -> dict[str, Any]:
        """Classify one station as detected, watch, clear or unassessed."""

        # Missing, future or stale observations cannot prove a clear condition.
        observed_at_value = snapshot.get("observed_at")
        if observed_at_value is None:
            return _unassessed(
                snapshot, "hydrometric_observation_unavailable"
            )
        if not isinstance(observed_at_value, datetime):
            return _unassessed(snapshot, "invalid_observation_timestamp")
        try:
            observed_at = _utc(observed_at_value, "observed_at")
        except ValueError:
            return _unassessed(snapshot, "invalid_observation_timestamp")

        age = checked_at - observed_at
        if age < timedelta(0) or age > self.policy.max_observation_age:
            return _unassessed(snapshot, "stale_observation")

        observations = _normalized_observations(snapshot, checked_at)
        if not observations:
            return _unassessed(snapshot, "hydrological_measurements_unavailable")

        latest = observations[-1]
        discharge = latest["discharge_m3s"]
        water_height = latest["water_height_m"]
        if discharge is None and water_height is None:
            return _unassessed(snapshot, "hydrological_measurements_unavailable")

        # Partial threshold sets remain useful; invalid sets are rejected.
        (
            threshold_status,
            thresholds,
            available_return_periods,
            missing_return_periods,
        ) = _validated_thresholds(snapshot)
        q2 = thresholds.get(2)
        crossed = [
            {"return_period_years": period, "threshold_m3s": threshold}
            for period, threshold in thresholds.items()
            if discharge is not None and discharge >= threshold
        ]
        highest_crossed = (
            max(item["return_period_years"] for item in crossed)
            if crossed
            else None
        )

        # Flow start is the station-specific stage at which channel flow begins.
        flow_start_level = _optional_float(
            snapshot.get("flow_start_water_level_m")
        )
        flow_started = (
            water_height >= flow_start_level
            if water_height is not None and flow_start_level is not None
            else None
        )
        trend = _trend_evidence(observations, q2)
        rapid_stage_rise = (
            trend["consecutive_stage_rises"]
            >= self.policy.minimum_consecutive_rises
            and trend["recent_stage_rise_m_per_hour"] is not None
            and trend["recent_stage_rise_m_per_hour"]
            >= self.policy.rapid_stage_rise_m_per_hour
        )
        rapid_discharge_rise = (
            trend["consecutive_discharge_rises"]
            >= self.policy.minimum_consecutive_rises
            and trend["recent_discharge_rise_q2_per_hour"] is not None
            and trend["recent_discharge_rise_q2_per_hour"]
            >= self.policy.rapid_discharge_rise_q2_per_hour
        )
        rapid_rise = rapid_stage_rise or rapid_discharge_rise
        q2_persistence = (
            _consecutive_threshold_observations(observations, q2)
            if q2 is not None
            else 0
        )
        threshold_persistent = (
            q2_persistence
            >= self.policy.threshold_persistence_observations
        )
        active_flow = flow_started is True or (
            flow_started is None and discharge is not None and discharge > 0
        )
        # Rainfall corroborates a hydrological signal but cannot create one.
        rainfall_evidence = _normalized_rainfall_evidence(snapshot)
        rainfall_context = _rainfall_context(
            rainfall_evidence,
            basin_id=snapshot.get("basin_id"),
            checked_at=checked_at,
            max_age=self.policy.max_rainfall_age,
        )

        detection_state, reasons = self._classify_state(
            discharge=discharge,
            thresholds=thresholds,
            threshold_status=threshold_status,
            threshold_persistent=threshold_persistent,
            rapid_rise=rapid_rise,
            active_flow=active_flow,
        )
        if rainfall_context["recent_rain_detected"]:
            reasons.append("recent_rainfall_in_same_drainage_basin")

        if detection_state == "data_uncertain":
            return _unassessed(
                snapshot,
                reasons[0],
                threshold_status=threshold_status,
                available_return_periods=available_return_periods,
                missing_return_periods=missing_return_periods,
                observation_count=len(observations),
            )
        if detection_state == "no_signal":
            # Clear stations are counted at scan level, not returned as events.
            return {"status": "clear"}

        latitude = _optional_float(snapshot.get("latitude"))
        longitude = _optional_float(snapshot.get("longitude"))
        location_known = latitude is not None and longitude is not None
        detected = detection_state != "flood_watch"
        confidence = _confidence(
            detection_state=detection_state,
            threshold_status=threshold_status,
            threshold_persistent=threshold_persistent,
            rapid_rise=rapid_rise,
            location_known=location_known,
            rainfall_supports_signal=rainfall_context[
                "recent_rain_detected"
            ],
        )

        # Event coordinates describe the gauge, not the inundated area.
        event = {
            "event_key": (
                "flood:water_authority:"
                f"{snapshot.get('source_station_id')}"
            ),
            "metadata": {
                "timestamp": checked_at.isoformat(),
                "collection_status": "success",
            },
            "event_type": "flood",
            "detected": detected,
            "detection_state": detection_state,
            "flow_intensity": _flow_intensity(
                discharge=discharge,
                water_height=water_height,
                flow_start_level=flow_start_level,
                thresholds=thresholds,
            ),
            "confidence": confidence,
            "reasons": reasons,
            "observed_at": observed_at.isoformat(),
            "location": {
                "known": location_known,
                "latitude": latitude,
                "longitude": longitude,
            },
            "station": {
                "source_station_id": snapshot.get("source_station_id"),
                "hydrometric_station_id": snapshot.get(
                    "hydrometric_station_id"
                ),
                "name_he": snapshot.get("station_name_he"),
                "name_en": snapshot.get("station_name_en"),
            },
            "drainage_basin": {
                "basin_id": snapshot.get("basin_id"),
                "name_he": snapshot.get("basin_name_he"),
                "name_en": snapshot.get("basin_name_en"),
            },
            "stream_context": _stream_context(snapshot, self.policy),
            "hydrological_evidence": {
                "discharge_m3s": discharge,
                "water_height_m": water_height,
                "flow_start_water_level_m": flow_start_level,
                "flow_started": flow_started,
                "threshold_status": threshold_status,
                "available_return_periods": available_return_periods,
                "missing_return_periods": missing_return_periods,
                "crossed_thresholds": crossed,
                "highest_crossed_return_period_years": highest_crossed,
                "q2_persistence_observations": q2_persistence,
                "rapid_stage_rise": rapid_stage_rise,
                "rapid_discharge_rise": rapid_discharge_rise,
                "trend": trend,
            },
            "rainfall_context": rainfall_context,
            "rainfall_evidence": _public_rainfall_evidence(
                rainfall_evidence
            ),
        }
        return {
            "status": "detected" if detected else "watch",
            "event": event,
        }

    def _classify_state(
        self,
        *,
        discharge: float | None,
        thresholds: dict[int, float],
        threshold_status: str,
        threshold_persistent: bool,
        rapid_rise: bool,
        active_flow: bool,
    ) -> tuple[str, list[str]]:
        """Apply detection rules from strong evidence to watch/no-signal."""

        q2 = thresholds.get(2)
        crossed_q2 = (
            discharge is not None and q2 is not None and discharge >= q2
        )
        crossed_high_flow_period = next(
            (
                period
                for period in RETURN_PERIODS
                if period >= 5
                and (threshold := thresholds.get(period)) is not None
                and discharge is not None
                and discharge >= threshold
            ),
            None,
        )

        if crossed_high_flow_period is not None:
            reasons = [
                "discharge_at_or_above_"
                f"{crossed_high_flow_period}_year_threshold"
            ]
            if threshold_persistent:
                reasons.append("discharge_threshold_crossing_persisted")
            if rapid_rise:
                reasons.append("rapid_persistent_hydrological_rise")
            return "observed_high_flow", reasons

        if crossed_q2 and threshold_persistent and rapid_rise:
            return "observed_high_flow", [
                "discharge_at_or_above_2_year_threshold",
                "discharge_threshold_crossing_persisted",
                "rapid_persistent_hydrological_rise",
            ]

        if crossed_q2 and threshold_persistent:
            return "flood_wave_likely", [
                "discharge_at_or_above_2_year_threshold",
                "discharge_threshold_crossing_persisted",
            ]

        if active_flow and rapid_rise:
            state = (
                "flood_wave_likely"
                if q2 is None
                else "rapid_flow_detected"
            )
            return state, [
                "active_flow",
                "rapid_persistent_hydrological_rise",
                f"discharge_thresholds_{threshold_status}",
            ]

        if crossed_q2:
            return "flood_watch", [
                "single_discharge_threshold_crossing_awaiting_persistence"
            ]

        if q2 is None and active_flow:
            return "data_uncertain", [
                "active_flow_without_usable_q2_threshold_or_trend"
            ]

        return "no_signal", []


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must carry a UTC offset")
    return value.astimezone(timezone.utc)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _normalized_observations(
    snapshot: dict[str, Any], checked_at: datetime
) -> list[dict[str, Any]]:
    """Clean, de-duplicate and time-sort a station's usable history."""

    raw_history = snapshot.get("observations")
    candidates = raw_history if isinstance(raw_history, list) else []
    candidates = [
        *candidates,
        {
            "observed_at": snapshot.get("observed_at"),
            "discharge_m3s": snapshot.get("discharge_m3s"),
            "water_height_m": snapshot.get("water_height_m"),
        },
    ]

    by_timestamp: dict[datetime, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        raw_time = candidate.get("observed_at")
        if not isinstance(raw_time, datetime):
            continue
        try:
            observed_at = _utc(raw_time, "observation history timestamp")
        except ValueError:
            continue
        if observed_at > checked_at:
            continue
        discharge = _optional_float(candidate.get("discharge_m3s"))
        water_height = _optional_float(candidate.get("water_height_m"))
        if discharge is None and water_height is None:
            continue
        by_timestamp[observed_at] = {
            "observed_at": observed_at,
            "discharge_m3s": discharge,
            "water_height_m": water_height,
        }
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def _validated_thresholds(
    snapshot: dict[str, Any],
) -> tuple[str, dict[int, float], list[int], list[int]]:
    """Keep only positive, monotonically increasing discharge thresholds."""

    values = {
        period: _optional_float(
            snapshot.get(f"flow_threshold_{period}y_m3s")
        )
        for period in RETURN_PERIODS
    }
    available = [
        period for period, value in values.items() if value is not None
    ]
    missing = [
        period for period, value in values.items() if value is None
    ]
    if not available:
        return "unavailable", {}, available, missing

    thresholds = {
        period: value
        for period in RETURN_PERIODS
        if (value := values[period]) is not None
    }
    ordered_values = list(thresholds.values())
    if any(value <= 0 for value in ordered_values):
        return "non_positive", {}, available, missing
    if any(
        later < earlier
        for earlier, later in zip(ordered_values, ordered_values[1:])
    ):
        return "non_monotonic", {}, available, missing

    status = "valid" if not missing else "partial"
    return status, thresholds, available, missing


def _consecutive_rises(
    observations: list[dict[str, Any]], field: str
) -> int:
    count = 0
    for previous, current in zip(
        reversed(observations[:-1]), reversed(observations[1:])
    ):
        previous_value = previous[field]
        current_value = current[field]
        if previous_value is None or current_value is None:
            break
        if current_value <= previous_value:
            break
        count += 1
    return count


def _recent_rate(
    observations: list[dict[str, Any]], field: str, rise_count: int
) -> float | None:
    if rise_count <= 0:
        return None
    start = observations[-1 - rise_count]
    end = observations[-1]
    start_value = start[field]
    end_value = end[field]
    elapsed_hours = (
        end["observed_at"] - start["observed_at"]
    ).total_seconds() / 3600
    if start_value is None or end_value is None or elapsed_hours <= 0:
        return None
    return (end_value - start_value) / elapsed_hours


def _window_changes(
    observations: list[dict[str, Any]], window_minutes: int
) -> dict[str, Any] | None:
    """Compare with the observation closest to the requested time window."""

    latest = observations[-1]
    target = timedelta(minutes=window_minutes)
    lower = target / 2
    upper = target * 1.5
    eligible = [
        observation
        for observation in observations[:-1]
        if lower
        <= latest["observed_at"] - observation["observed_at"]
        <= upper
    ]
    if not eligible:
        return None
    start = min(
        eligible,
        key=lambda item: abs(
            (latest["observed_at"] - item["observed_at"] - target).total_seconds()
        ),
    )
    elapsed_minutes = (
        latest["observed_at"] - start["observed_at"]
    ).total_seconds() / 60
    result: dict[str, Any] = {
        "elapsed_minutes": elapsed_minutes,
        "start_observed_at": start["observed_at"].isoformat(),
    }
    for field, output_name in (
        ("water_height_m", "water_height_change_m"),
        ("discharge_m3s", "discharge_change_m3s"),
    ):
        start_value = start[field]
        end_value = latest[field]
        result[output_name] = (
            end_value - start_value
            if start_value is not None and end_value is not None
            else None
        )
    return result


def _trend_evidence(
    observations: list[dict[str, Any]], q2: float | None
) -> dict[str, Any]:
    """Summarize consecutive rises, hourly rates and fixed-window changes."""

    stage_rises = _consecutive_rises(observations, "water_height_m")
    discharge_rises = _consecutive_rises(observations, "discharge_m3s")
    stage_rate = _recent_rate(observations, "water_height_m", stage_rises)
    discharge_rate = _recent_rate(
        observations, "discharge_m3s", discharge_rises
    )
    return {
        "observation_count": len(observations),
        "consecutive_stage_rises": stage_rises,
        "consecutive_discharge_rises": discharge_rises,
        "recent_stage_rise_m_per_hour": stage_rate,
        "recent_discharge_rise_m3s_per_hour": discharge_rate,
        "recent_discharge_rise_q2_per_hour": (
            discharge_rate / q2
            if discharge_rate is not None and q2 is not None and q2 > 0
            else None
        ),
        "changes": {
            f"{minutes}m": _window_changes(observations, minutes)
            for minutes in TREND_WINDOWS_MINUTES
        },
    }


def _consecutive_threshold_observations(
    observations: list[dict[str, Any]], threshold: float
) -> int:
    count = 0
    for observation in reversed(observations):
        discharge = observation["discharge_m3s"]
        if discharge is None or discharge < threshold:
            break
        count += 1
    return count


def _flow_intensity(
    *,
    discharge: float | None,
    water_height: float | None,
    flow_start_level: float | None,
    thresholds: dict[int, float],
) -> str:
    """Rank current flow rarity; this is not flood damage severity."""

    flow_below_start = (
        water_height is not None
        and flow_start_level is not None
        and water_height < flow_start_level
    )
    if thresholds and discharge is not None:
        for period, intensity in (
            (50, "extreme"),
            (20, "very_high"),
            (10, "high"),
            (5, "medium"),
            (2, "low"),
        ):
            threshold = thresholds.get(period)
            if threshold is not None and discharge >= threshold:
                return intensity
        return "negligible" if flow_below_start else "low"
    return "negligible" if flow_below_start else "unranked"


def _confidence(
    *,
    detection_state: str,
    threshold_status: str,
    threshold_persistent: bool,
    rapid_rise: bool,
    location_known: bool,
    rainfall_supports_signal: bool,
) -> str:
    """Rate evidence quality, not the probability or severity of flooding."""

    thresholds_usable = threshold_status in {"valid", "partial"}
    if detection_state == "flood_watch":
        return "low"
    if (
        thresholds_usable
        and threshold_persistent
        and location_known
    ):
        return "high"
    if rapid_rise and rainfall_supports_signal and location_known:
        return "high"
    if rapid_rise and location_known:
        return "medium"
    return "medium" if thresholds_usable else "low"


_GENERIC_STREAM_NAME_TOKENS = frozenset(
    {"נחל", "נהר", "ואדי", "wadi", "nahal", "river", "stream"}
)


def _name_tokens(value: Any) -> tuple[str, ...]:
    """Normalize names while ignoring generic words such as river or wadi."""

    if not isinstance(value, str):
        return ()
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(
        token
        for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        if token not in _GENERIC_STREAM_NAME_TOKENS
    )


def _stream_name_matches_station(
    candidate: dict[str, Any], snapshot: dict[str, Any]
) -> bool:
    stream_tokens = _name_tokens(candidate.get("name_he"))
    if not stream_tokens:
        return False
    for field in ("station_name_he", "station_name_en"):
        station_tokens = set(_name_tokens(snapshot.get(field)))
        if station_tokens and all(
            token in station_tokens for token in stream_tokens
        ):
            return True
    return False


def _normalized_stream_candidates(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate nearby stream candidates and sort them by distance."""

    raw_candidates = snapshot.get("stream_candidates")
    if not isinstance(raw_candidates, list):
        return []
    candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        distance = _nonnegative_float(raw.get("distance_m"))
        if distance is None:
            continue
        candidate = {
            "stream_id": raw.get("stream_id"),
            "object_id": raw.get("object_id"),
            "name_he": raw.get("name_he"),
            "water_source_id": raw.get("water_source_id"),
            "main_catchment_code": raw.get("main_catchment_code"),
            "main_catchment_name": raw.get("main_catchment_name"),
            "draining_water_id": raw.get("draining_water_id"),
            "draining_water_name": raw.get("draining_water_name"),
            "distance_m": distance,
        }
        candidate["name_matches_station"] = (
            _stream_name_matches_station(candidate, snapshot)
        )
        candidates.append(candidate)
    return sorted(
        candidates,
        key=lambda item: (
            item["distance_m"],
            item.get("object_id") is None,
            str(item.get("object_id")),
        ),
    )


def _stream_identity(candidate: dict[str, Any]) -> tuple[str, Any]:
    """Identify one river across multiple GeoJSON line segments."""

    water_source_id = candidate.get("water_source_id")
    if water_source_id is not None:
        return "water_source_id", water_source_id
    name_tokens = _name_tokens(candidate.get("name_he"))
    if name_tokens:
        return "name", name_tokens
    return "object_id", candidate.get("object_id")


def _distinct_stream_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse map segments that carry the same source river identity."""
    distinct: dict[tuple[str, Any], dict[str, Any]] = {}
    for candidate in candidates:
        distinct.setdefault(_stream_identity(candidate), candidate)
    return list(distinct.values())


def _public_stream(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        **candidate,
        "distance_m": round(candidate["distance_m"], 1),
    }


def _stream_context(
    snapshot: dict[str, Any], policy: FloodDetectionPolicy
) -> dict[str, Any]:
    """Resolve a station to a river conservatively within its own basin.

    Distance alone is accepted only when the station is very close to the
    mapped channel. At larger distances an exact token match between the
    station and stream names is required. Ambiguous results remain unresolved
    so later routing never starts from a confidently wrong river.
    """
    result: dict[str, Any] = {
        "association": "same_drainage_basin",
        "matched": False,
        "confidence": "unavailable",
        "method": None,
        "candidate_count": 0,
        "distinct_candidate_count": 0,
        "stream": None,
        "nearest_candidate": None,
        "warnings": [],
    }
    if (
        _optional_float(snapshot.get("latitude")) is None
        or _optional_float(snapshot.get("longitude")) is None
    ):
        result["association"] = "unavailable"
        result["warnings"].append("station_location_unavailable")
        return result
    if snapshot.get("basin_id") is None:
        result["association"] = "unavailable"
        result["warnings"].append("drainage_basin_unavailable")
        return result

    candidates = _normalized_stream_candidates(snapshot)
    distinct = _distinct_stream_candidates(candidates)
    result["candidate_count"] = len(candidates)
    result["distinct_candidate_count"] = len(distinct)
    if len(candidates) >= policy.stream_candidate_limit:
        result["warnings"].append("stream_candidate_limit_reached")
    if not distinct:
        result["confidence"] = "low"
        result["warnings"].append("no_stream_candidate_in_same_basin")
        return result

    nearest = distinct[0]
    reliable = [
        candidate
        for candidate in distinct
        if candidate["distance_m"]
        <= policy.max_reliable_stream_distance_m
    ]
    if not reliable:
        result["confidence"] = "low"
        result["nearest_candidate"] = _public_stream(nearest)
        result["warnings"].append(
            "nearest_stream_beyond_reliable_distance"
        )
        return result

    nearest = reliable[0]
    name_matches = [
        candidate
        for candidate in reliable
        if candidate["name_matches_station"]
    ]
    selected = nearest
    method = "same_basin_distance_only"
    if name_matches:
        nearest_name_match = name_matches[0]
        maximum_override_distance = max(
            policy.strong_stream_distance_m,
            nearest["distance_m"]
            * policy.stream_name_override_distance_factor,
        )
        if nearest_name_match["distance_m"] <= maximum_override_distance:
            selected = nearest_name_match
            method = "same_basin_name_and_distance"
        else:
            result["warnings"].append(
                "name_matching_stream_is_much_farther"
            )

    comparable = [
        candidate
        for candidate in reliable
        if _stream_identity(candidate) != _stream_identity(selected)
        and (
            not selected["name_matches_station"]
            or candidate["name_matches_station"]
        )
    ]
    ambiguous = any(
        abs(candidate["distance_m"] - selected["distance_m"])
        <= policy.stream_ambiguity_distance_m
        for candidate in comparable
    )
    if ambiguous:
        result["confidence"] = "low"
        result["method"] = method
        result["nearest_candidate"] = _public_stream(selected)
        result["warnings"].append("multiple_similarly_close_streams")
        return result

    if not selected["name_matches_station"]:
        result["warnings"].append(
            "station_and_stream_names_do_not_match"
        )
    if (
        selected["distance_m"] <= policy.strong_stream_distance_m
        and selected["name_matches_station"]
    ):
        confidence = "high"
    elif (
        selected["distance_m"] <= policy.strong_stream_distance_m
        or selected["name_matches_station"]
    ):
        confidence = "medium"
    else:
        confidence = "low"

    result["confidence"] = confidence
    result["method"] = method
    if confidence in {"high", "medium"}:
        result["matched"] = True
        result["stream"] = _public_stream(selected)
    else:
        result["nearest_candidate"] = _public_stream(selected)
        result["warnings"].append(
            "distance_only_match_is_not_reliable"
        )
    return result


def _optional_identifier(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _downstream_route(
    stream_context: dict[str, Any],
    network: dict[int, dict[str, Any]],
    *,
    max_hops: int,
    network_available: bool,
) -> dict[str, Any]:
    """Follow provider-declared downstream ids without inferring line order."""
    result: dict[str, Any] = {
        "status": "unavailable",
        "confidence": "unavailable",
        "method": "water_authority_draining_water_id",
        "origin_water_source_id": None,
        "segment_count": 0,
        "segments": [],
        "termination": "origin_stream_unmatched",
        "limitations": [
            "route_uses_declared_connections_not_hydraulic_simulation",
            "coordinate_order_is_not_used_as_flow_direction",
            "route_does_not_predict_inundation_extent_or_travel_time",
            "representative_points_are_not_flood_boundaries",
        ],
    }
    if not stream_context.get("matched"):
        return result
    stream = stream_context.get("stream")
    if not isinstance(stream, dict):
        return result
    origin_id = _optional_identifier(stream.get("water_source_id"))
    result["origin_water_source_id"] = origin_id
    result["confidence"] = stream_context.get("confidence", "unavailable")
    if origin_id is None:
        result["termination"] = "origin_water_source_id_unavailable"
        return result
    if not network_available:
        result["termination"] = "stream_network_unavailable"
        return result

    if not network:
        result["termination"] = "stream_network_empty"
        return result

    current_id = origin_id
    visited: set[int] = set()
    segments: list[dict[str, Any]] = []
    termination = "maximum_hops_reached"
    status = "partial"
    for hop in range(max_hops + 1):
        if current_id in visited:
            termination = "cycle_detected"
            result["confidence"] = "low"
            break
        node = network.get(current_id)
        if node is None:
            termination = (
                "origin_stream_missing_from_network"
                if hop == 0
                else "downstream_stream_missing_from_network"
            )
            break

        visited.add(current_id)
        segment = {"hop": hop, **node}
        if hop == 0:
            segment["matched_object_id"] = stream.get("object_id")
        segments.append(segment)

        if node["topology_conflict"]:
            termination = "conflicting_downstream_connections"
            result["confidence"] = "low"
            break
        next_id = node["draining_water_id"]
        if next_id is None:
            termination = "declared_network_end"
            status = "complete"
            break
        if hop == max_hops:
            termination = "maximum_hops_reached"
            break
        current_id = next_id

    result["status"] = status if segments else "unavailable"
    result["segment_count"] = len(segments)
    result["segments"] = segments
    result["termination"] = termination
    return result


def _normalized_rainfall_evidence(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize basin rain gauges without converting missing values to zero."""

    evidence = snapshot.get("rainfall_evidence")
    if not isinstance(evidence, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        observed_at = _optional_timestamp(item.get("latest_observed_at"))
        normalized.append(
            {
                "source_station_id": item.get("source_station_id"),
                "name_he": item.get("name_he"),
                "name_en": item.get("name_en"),
                "latitude": _optional_float(item.get("latitude")),
                "longitude": _optional_float(item.get("longitude")),
                "latest_observed_at": observed_at,
                **{
                    field: _nonnegative_float(item.get(field))
                    for field in (
                        "rainfall_10m_mm",
                        "rainfall_1h_mm",
                        "rainfall_6h_mm",
                        "rainfall_24h_mm",
                    )
                },
            }
        )
    return normalized


def _public_rainfall_evidence(
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "latest_observed_at": (
                item["latest_observed_at"].isoformat()
                if item["latest_observed_at"] is not None
                else None
            ),
        }
        for item in evidence
    ]


def _optional_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        try:
            return _utc(value, "rainfall observation timestamp")
        except ValueError:
            return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _utc(parsed, "rainfall observation timestamp")
    except ValueError:
        return None


def _cache_health_from_timestamps(
    timestamps_by_station: dict[Any, datetime],
    *,
    checked_at: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    """Describe cache coverage from the latest timestamp per station."""

    timestamps = list(timestamps_by_station.values())
    fresh = [
        timestamp
        for timestamp in timestamps
        if timedelta(0) <= checked_at - timestamp <= max_age
    ]
    if not timestamps:
        coverage = "unavailable"
    elif len(fresh) == len(timestamps):
        coverage = "fresh"
    elif fresh:
        coverage = "partial"
    else:
        coverage = "stale"
    return {
        "cached_data_available": bool(timestamps),
        "cached_data_fresh": bool(fresh),
        "cache_coverage": coverage,
        "cached_station_count": len(timestamps),
        "fresh_station_count": len(fresh),
        "latest_observed_at": (
            max(timestamps).isoformat() if timestamps else None
        ),
    }


def _hydrometric_cache_health(
    histories: list[dict[str, Any]],
    *,
    checked_at: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    timestamps: dict[Any, datetime] = {}
    for index, snapshot in enumerate(histories):
        observed_at = _optional_timestamp(snapshot.get("observed_at"))
        if observed_at is None:
            continue
        key = snapshot.get("source_station_id")
        if key is None:
            key = ("unknown_station", index)
        previous = timestamps.get(key)
        if previous is None or observed_at > previous:
            timestamps[key] = observed_at
    return _cache_health_from_timestamps(
        timestamps,
        checked_at=checked_at,
        max_age=max_age,
    )


def _rainfall_cache_health(
    histories: list[dict[str, Any]],
    *,
    checked_at: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    timestamps: dict[Any, datetime] = {}
    for history_index, snapshot in enumerate(histories):
        raw_evidence = snapshot.get("rainfall_evidence")
        if not isinstance(raw_evidence, list):
            continue
        for evidence_index, item in enumerate(raw_evidence):
            if not isinstance(item, dict):
                continue
            observed_at = _optional_timestamp(
                item.get("latest_observed_at")
            )
            if observed_at is None:
                continue
            key = item.get("source_station_id")
            if key is None:
                key = (
                    "unknown_rain_station",
                    history_index,
                    evidence_index,
                )
            previous = timestamps.get(key)
            if previous is None or observed_at > previous:
                timestamps[key] = observed_at
    return _cache_health_from_timestamps(
        timestamps,
        checked_at=checked_at,
        max_age=max_age,
    )


def _collector_source_health(
    *,
    source: str,
    latest_run: dict[str, Any] | None,
    cache: dict[str, Any],
    run_history_available: bool,
) -> dict[str, Any]:
    """Combine collector-run status with actual cached-data freshness."""

    latest_status: str | None = None
    if isinstance(latest_run, dict) and isinstance(
        latest_run.get("status"), str
    ):
        latest_status = latest_run["status"].strip().lower() or None

    coverage = cache["cache_coverage"]
    if not run_history_available:
        status = "unknown"
    elif latest_run is None:
        status = "never_run"
    elif latest_status == "failed":
        status = "degraded" if cache["cached_data_fresh"] else "failed"
    elif latest_status == "ok":
        status = {
            "fresh": "success",
            "partial": "degraded",
            "stale": "stale",
            "unavailable": "unavailable",
        }[coverage]
    elif latest_status == "running":
        status = {
            "fresh": "success",
            "partial": "degraded",
            "stale": "collecting",
            "unavailable": "collecting",
        }[coverage]
    else:
        status = "degraded" if cache["cached_data_fresh"] else "unknown"

    started_at = (
        _optional_timestamp(latest_run.get("started_at"))
        if isinstance(latest_run, dict)
        else None
    )
    finished_at = (
        _optional_timestamp(latest_run.get("finished_at"))
        if isinstance(latest_run, dict)
        else None
    )
    return {
        "status": status,
        "collector_source": source,
        "latest_collection_status": latest_status,
        "latest_started_at": (
            started_at.isoformat() if started_at is not None else None
        ),
        "latest_finished_at": (
            finished_at.isoformat() if finished_at is not None else None
        ),
        "latest_rows_written": (
            latest_run.get("rows_written")
            if isinstance(latest_run, dict)
            else None
        ),
        "latest_run_has_error": bool(
            isinstance(latest_run, dict) and latest_run.get("error")
        ),
        **cache,
    }


def _rainfall_context(
    evidence: list[dict[str, Any]],
    *,
    basin_id: Any,
    checked_at: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    """Summarise gauges spatially assigned to the station's drainage basin.

    Values from different gauges are never summed: doing so would count the
    same storm multiple times. Basin context reports maxima and means instead.
    """
    timestamps = [
        item["latest_observed_at"]
        for item in evidence
        if item["latest_observed_at"] is not None
    ]
    fresh = [
        item
        for item in evidence
        if item["latest_observed_at"] is not None
        and timedelta(0)
        <= checked_at - item["latest_observed_at"]
        <= max_age
    ]
    summary: dict[str, Any] = {
        "association": (
            "same_drainage_basin"
            if basin_id is not None
            else "unavailable"
        ),
        "basin_id": basin_id,
        "station_count": len(evidence),
        "stations_with_observations": len(timestamps),
        "fresh_station_count": len(fresh),
        "latest_observation_at": (
            max(timestamps).isoformat() if timestamps else None
        ),
        "is_fresh": bool(fresh),
        "recent_rain_detected": any(
            (item["rainfall_1h_mm"] or 0) > 0 for item in fresh
        ),
        "limitations": [
            "same_basin_does_not_prove_upstream_subcatchment",
            "rainfall_has_not_yet_been_compared_with_local_idf",
        ],
    }
    for field in (
        "rainfall_10m_mm",
        "rainfall_1h_mm",
        "rainfall_6h_mm",
        "rainfall_24h_mm",
    ):
        values = [item[field] for item in fresh if item[field] is not None]
        period = field.removeprefix("rainfall_").removesuffix("_mm")
        summary[f"maximum_{period}_mm"] = max(values) if values else None
        summary[f"mean_{period}_mm"] = (
            sum(values) / len(values) if values else None
        )
    return summary


def _nonnegative_float(value: Any) -> float | None:
    result = _optional_float(value)
    return result if result is not None and result >= 0 else None


def _unassessed(
    snapshot: dict[str, Any],
    reason: str,
    **details: Any,
) -> dict[str, Any]:
    """Retain provider readings even when they cannot be classified."""
    observed_at = snapshot.get("observed_at")
    return {
        "status": "unassessed",
        "station": {
            "source_station_id": snapshot.get("source_station_id"),
            "hydrometric_station_id": snapshot.get("hydrometric_station_id"),
            "observed_at": (
                observed_at.isoformat()
                if isinstance(observed_at, datetime)
                else observed_at
            ),
            "discharge_m3s": snapshot.get("discharge_m3s"),
            "water_height_m": snapshot.get("water_height_m"),
            "location_known": (
                snapshot.get("latitude") is not None
                and snapshot.get("longitude") is not None
            ),
            "reason": reason,
            **details,
        },
    }
