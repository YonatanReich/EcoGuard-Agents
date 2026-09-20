"""Deterministic event analysis for an existing hydrometric Flood incident."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ecoguard.analyzers.emergency.flood.event_analysis_schemas import (
    CurrentHydrologicState,
    FloodChangeAssessment,
    FloodEventAnalysis,
    FloodProgressionAssessment,
    HydrometricStationState,
)


ANALYZER_LIMITATIONS = [
    "Hydrologic state is derived from persisted gauge signals and does not confirm inundation extent.",
    "Road flooding, safety, and passability are not established by this analysis.",
]

RETURN_PERIOD_BY_SEVERITY: dict[int, int | None] = {
    0: None,
    1: 2,
    2: 5,
    3: 10,
    4: 20,
    5: 50,
    6: 100,
}

ALERT_BY_SEVERITY = {
    0: "none",
    1: "none",
    2: "monitoring",
    3: "active",
    4: "severe",
    5: "emergency",
    6: "emergency",
}

THRESHOLD_LABEL_BY_SEVERITY = {
    0: "below_Q2",
    1: "Q2",
    2: "Q5",
    3: "Q10",
    4: "Q20",
    5: "Q50",
    6: "Q100",
}


@dataclass(frozen=True)
class _ParsedSignal:
    ordinal: int
    station_id: int
    stream_id: int | None
    cell_id: str
    observed_at: datetime
    latitude: float | None
    longitude: float | None
    precision_m: float
    current_discharge_m3s: float
    previous_discharge_m3s: float | None
    severity_level: int
    threshold_vector_m3s: list[float] | None
    confidence: float | None

    def station_state(self) -> HydrometricStationState:
        return HydrometricStationState(
            station_id=self.station_id,
            stream_id=self.stream_id,
            cell_id=self.cell_id,
            observed_at=self.observed_at,
            latitude=self.latitude,
            longitude=self.longitude,
            precision_m=self.precision_m,
            current_discharge_m3s=self.current_discharge_m3s,
            previous_discharge_m3s=self.previous_discharge_m3s,
            severity_level=self.severity_level,
            return_period_years=RETURN_PERIOD_BY_SEVERITY[self.severity_level],
            alert_level=ALERT_BY_SEVERITY[self.severity_level],
            threshold_vector_m3s=self.threshold_vector_m3s,
            confidence=self.confidence,
        )


class FloodEventAnalyzer:
    """Analyze persisted Flood signals without detection, planning, or LLM use."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._clock = clock

    def analyze(self, incident: Mapping[str, Any]) -> FloodEventAnalysis:
        """Return the current state and the change introduced by the latest signal."""

        incident_id = str(incident.get("id") or "").strip()
        if not incident_id:
            raise ValueError("Flood incident id is required")

        parsed, invalid_count, duplicate_count = self._signals(incident)
        generated_at = self._now()
        if not parsed:
            return FloodEventAnalysis(
                incident_id=incident_id,
                generated_at=generated_at,
                status="unavailable",
                evidence_gaps=["No valid persisted hydrometric Flood signals were available."],
                limitations=list(ANALYZER_LIMITATIONS),
                invalid_signal_count=invalid_count,
                duplicate_signal_count=duplicate_count,
            )

        current_by_station = self._latest_by_station(parsed)
        previous_by_station = self._latest_by_station(parsed[:-1])
        current_state = self._current_state(current_by_station)
        progression = self._progression(parsed[-1])
        change = self._change_assessment(
            latest=parsed[-1],
            current_by_station=current_by_station,
            previous_by_station=previous_by_station,
        )
        gaps = self._evidence_gaps(current_by_station, progression, invalid_count)
        return FloodEventAnalysis(
            incident_id=incident_id,
            generated_at=generated_at,
            status="partial" if gaps else "success",
            current_state=current_state,
            progression_assessment=progression,
            change_assessment=change,
            evidence_gaps=gaps,
            limitations=list(ANALYZER_LIMITATIONS),
            invalid_signal_count=invalid_count,
            duplicate_signal_count=duplicate_count,
        )

    def _signals(
        self, incident: Mapping[str, Any]
    ) -> tuple[list[_ParsedSignal], int, int]:
        raw_signals = incident.get("signals") or []
        if not isinstance(raw_signals, Sequence) or isinstance(
            raw_signals, (str, bytes)
        ):
            return [], 1, 0

        parsed: list[_ParsedSignal] = []
        invalid_count = 0
        for ordinal, raw in enumerate(raw_signals):
            if not isinstance(raw, Mapping) or raw.get("hazard") != "flood":
                continue
            signal = self._parse_signal(raw, ordinal)
            if signal is None:
                invalid_count += 1
            else:
                parsed.append(signal)

        # A retry must not create a false progression step. The detector's
        # stable identity at this boundary is station plus observation time.
        unique: dict[tuple[int, datetime], _ParsedSignal] = {}
        for signal in parsed:
            unique[(signal.station_id, signal.observed_at)] = signal
        duplicate_count = len(parsed) - len(unique)
        ordered = sorted(unique.values(), key=lambda item: (item.observed_at, item.ordinal))
        return ordered, invalid_count, duplicate_count

    def _parse_signal(
        self, raw: Mapping[str, Any], ordinal: int
    ) -> _ParsedSignal | None:
        evidence = raw.get("evidence")
        if not isinstance(evidence, Mapping):
            return None
        location = raw.get("location")
        if not isinstance(location, Mapping):
            location = {}

        try:
            station_id = self._integer(
                evidence.get("source_station_id", evidence.get("station_id")),
                minimum=1,
            )
            severity = self._integer(evidence.get("severity_level"), minimum=0)
            if severity > 6:
                return None
            observed_at = self._datetime(
                raw.get("observed_at", evidence.get("timestamp"))
            )
            discharge = self._number(
                evidence.get("current_discharge", raw.get("value")), minimum=0
            )
            thresholds = self._threshold_vector(evidence.get("threshold_vector_m3s"))
            if thresholds is None:
                return None
            # The vector is the official source of the band. Reject an
            # internally inconsistent detector payload instead of carrying a
            # plausible-looking but incorrect severity into operations.
            derived_severity = sum(discharge >= threshold for threshold in thresholds)
            if severity != derived_severity:
                return None
            cell_id = str(raw.get("cell_id") or "").strip()
            if not cell_id:
                return None
        except (TypeError, ValueError):
            return None

        recent = evidence.get("recent_discharges_m3s")
        previous_discharge = None
        if isinstance(recent, Sequence) and not isinstance(recent, (str, bytes)):
            if len(recent) >= 2:
                try:
                    previous_discharge = self._number(recent[-2], minimum=0)
                except (TypeError, ValueError):
                    previous_discharge = None

        stream_id = self._optional_integer(evidence.get("stream_id"), minimum=1)
        latitude = self._optional_number(location.get("latitude"), minimum=-90, maximum=90)
        longitude = self._optional_number(
            location.get("longitude"), minimum=-180, maximum=180
        )
        precision_m = self._optional_number(location.get("precision_m"), minimum=0)
        confidence = self._optional_number(raw.get("confidence"), minimum=0, maximum=1)

        return _ParsedSignal(
            ordinal=ordinal,
            station_id=station_id,
            stream_id=stream_id,
            cell_id=cell_id,
            observed_at=observed_at,
            latitude=latitude,
            longitude=longitude,
            precision_m=precision_m or 0.0,
            current_discharge_m3s=discharge,
            previous_discharge_m3s=previous_discharge,
            severity_level=severity,
            threshold_vector_m3s=thresholds,
            confidence=confidence,
        )

    @staticmethod
    def _latest_by_station(
        signals: Sequence[_ParsedSignal],
    ) -> dict[int, _ParsedSignal]:
        latest: dict[int, _ParsedSignal] = {}
        for signal in signals:
            latest[signal.station_id] = signal
        return latest

    @staticmethod
    def _primary(signals: Sequence[_ParsedSignal]) -> _ParsedSignal:
        return max(
            signals,
            key=lambda item: (item.severity_level, item.observed_at, item.station_id),
        )

    def _current_state(
        self, current_by_station: Mapping[int, _ParsedSignal]
    ) -> CurrentHydrologicState:
        latest = list(current_by_station.values())
        primary = self._primary(latest)
        states = [item.station_state() for item in sorted(latest, key=lambda x: x.station_id)]
        return CurrentHydrologicState(
            primary_station_id=primary.station_id,
            observed_at=max(item.observed_at for item in latest),
            severity_level=primary.severity_level,
            return_period_years=RETURN_PERIOD_BY_SEVERITY[primary.severity_level],
            alert_level=ALERT_BY_SEVERITY[primary.severity_level],
            station_count=len(states),
            cells=sorted({item.cell_id for item in latest}),
            stations=states,
        )

    @staticmethod
    def _progression(latest: _ParsedSignal) -> FloodProgressionAssessment:
        previous = latest.previous_discharge_m3s
        if previous is None:
            trend = "unknown"
            delta = None
        else:
            delta = latest.current_discharge_m3s - previous
            if math.isclose(delta, 0.0, abs_tol=1e-9):
                trend = "stable"
                delta = 0.0
            else:
                trend = "rising" if delta > 0 else "falling"
        return FloodProgressionAssessment(
            station_id=latest.station_id,
            trend=trend,
            previous_discharge_m3s=previous,
            current_discharge_m3s=latest.current_discharge_m3s,
            discharge_change_m3s=delta,
        )

    def _change_assessment(
        self,
        *,
        latest: _ParsedSignal,
        current_by_station: Mapping[int, _ParsedSignal],
        previous_by_station: Mapping[int, _ParsedSignal],
    ) -> FloodChangeAssessment:
        current_severity = self._primary(list(current_by_station.values())).severity_level
        if not previous_by_station:
            return FloodChangeAssessment(
                change_type="initial",
                material_change=True,
                previous_severity_level=None,
                current_severity_level=current_severity,
                new_station_ids=[latest.station_id],
                new_cell_ids=[latest.cell_id],
                reasons=["initial_hydrometric_state_established"],
            )

        previous_severity = self._primary(list(previous_by_station.values())).severity_level
        previous_station_ids = set(previous_by_station)
        previous_cells = {item.cell_id for item in previous_by_station.values()}
        new_stations = sorted(set(current_by_station) - previous_station_ids)
        new_cells = sorted(
            {item.cell_id for item in current_by_station.values()} - previous_cells
        )

        transition = None
        reasons: list[str] = []
        if current_severity != previous_severity:
            transition = (
                f"{THRESHOLD_LABEL_BY_SEVERITY[previous_severity]}_to_"
                f"{THRESHOLD_LABEL_BY_SEVERITY[current_severity]}"
            )
            if current_severity > previous_severity:
                change_type = "escalated"
                reasons.append("official_return_period_threshold_increased")
            else:
                change_type = "deescalated"
                reasons.append("official_return_period_threshold_decreased")
            material = True
        elif new_stations or new_cells:
            change_type = "updated"
            material = True
            if new_stations:
                reasons.append("new_hydrometric_station_observed")
            if new_cells:
                reasons.append("incident_spatial_footprint_expanded")
        else:
            change_type = "no_material_change"
            material = False
            reasons.append("severity_and_observed_footprint_unchanged")

        return FloodChangeAssessment(
            change_type=change_type,
            material_change=material,
            previous_severity_level=previous_severity,
            current_severity_level=current_severity,
            threshold_transition=transition,
            new_station_ids=new_stations,
            new_cell_ids=new_cells,
            reasons=reasons,
        )

    @staticmethod
    def _evidence_gaps(
        current_by_station: Mapping[int, _ParsedSignal],
        progression: FloodProgressionAssessment,
        invalid_count: int,
    ) -> list[str]:
        gaps: list[str] = []
        missing_stream = sorted(
            item.station_id
            for item in current_by_station.values()
            if item.stream_id is None
        )
        if missing_stream:
            gaps.append(
                "Stream identity unavailable for station(s): "
                + ", ".join(str(item) for item in missing_stream)
                + "."
            )
        missing_location = sorted(
            item.station_id
            for item in current_by_station.values()
            if item.latitude is None or item.longitude is None
        )
        if missing_location:
            gaps.append(
                "Station coordinates unavailable for station(s): "
                + ", ".join(str(item) for item in missing_location)
                + "."
            )
        if progression.trend == "unknown":
            gaps.append("A preceding discharge value was unavailable for trend assessment.")
        if invalid_count:
            gaps.append(f"{invalid_count} malformed Flood signal(s) were ignored.")
        return gaps

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Flood analyzer clock must carry a UTC offset")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise TypeError("timestamp is unavailable")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must carry a UTC offset")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _number(
        value: object,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("numeric value required")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("numeric value must be finite")
        if minimum is not None and numeric < minimum:
            raise ValueError("numeric value below minimum")
        if maximum is not None and numeric > maximum:
            raise ValueError("numeric value above maximum")
        return numeric

    @classmethod
    def _optional_number(
        cls,
        value: object,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float | None:
        if value is None:
            return None
        try:
            return cls._number(value, minimum=minimum, maximum=maximum)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value: object, *, minimum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError("integer value required")
        return value

    @classmethod
    def _optional_integer(cls, value: object, *, minimum: int) -> int | None:
        if value is None:
            return None
        try:
            return cls._integer(value, minimum=minimum)
        except ValueError:
            return None

    @classmethod
    def _threshold_vector(cls, value: object) -> list[float] | None:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return None
        if len(value) != 6:
            return None
        try:
            thresholds = [cls._number(item, minimum=0) for item in value]
        except (TypeError, ValueError):
            return None
        if any(current <= previous for previous, current in zip(thresholds, thresholds[1:])):
            return None
        return thresholds


__all__ = [
    "ALERT_BY_SEVERITY",
    "ANALYZER_LIMITATIONS",
    "FloodEventAnalyzer",
    "RETURN_PERIOD_BY_SEVERITY",
]
