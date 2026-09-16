"""Adapt qualified Air Pollution evidence to the shared Coordinator signal."""

from __future__ import annotations

from typing import Any

from ecoguard.detectors.air_pollution.correlation import (
    PollutionCorrelationCandidate,
    correlation_candidate,
)
from ecoguard.detectors.air_pollution.schemas import AirPollutionDetectionResult
from ecoguard.shared.cells import cell_for
from ecoguard.shared.signals import (
    AIR_POLLUTION,
    HIGH,
    CellLocation,
    CellSignal,
)

ADAPTER_VERSION = "air-pollution-cell-signal-v1"


class AirPollutionCellSignalAdapterError(ValueError):
    """A qualified anomaly cannot safely enter the shared Coordinator."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def air_pollution_detection_to_cell_signal(
    detection: AirPollutionDetectionResult,
    *,
    candidate: PollutionCorrelationCandidate | None = None,
) -> CellSignal:
    """Adapt one detector-qualified result without re-running detection."""

    if not isinstance(detection, AirPollutionDetectionResult):
        raise AirPollutionCellSignalAdapterError("invalid_detection_result")
    if detection.status != "SUSPECTED_ANOMALY" or detection.anomaly is None:
        raise AirPollutionCellSignalAdapterError("detection_not_qualified")

    candidate = (
        correlation_candidate(detection.anomaly)
        if candidate is None
        else PollutionCorrelationCandidate.model_validate(
            candidate.model_dump(round_trip=True)
        )
    )
    if candidate.anomaly != detection.anomaly:
        raise AirPollutionCellSignalAdapterError("candidate_detection_mismatch")
    return _candidate_to_signal(
        candidate,
        detection_evidence=detection.model_dump(mode="json"),
    )


def air_pollution_candidate_to_cell_signal(
    candidate: PollutionCorrelationCandidate,
) -> CellSignal:
    """Adapt a qualified correlation candidate, retaining optional spatial context."""

    if not isinstance(candidate, PollutionCorrelationCandidate):
        raise AirPollutionCellSignalAdapterError("invalid_correlation_candidate")
    validated = PollutionCorrelationCandidate.model_validate(
        candidate.model_dump(round_trip=True)
    )
    return _candidate_to_signal(validated)


def _candidate_to_signal(
    candidate: PollutionCorrelationCandidate,
    *,
    detection_evidence: dict[str, Any] | None = None,
) -> CellSignal:
    anomaly = candidate.anomaly
    latitude = anomaly.location.latitude
    longitude = anomaly.location.longitude
    cell_id = cell_for(latitude, longitude)
    if cell_id is None:
        raise AirPollutionCellSignalAdapterError(
            "monitoring_station_outside_service_area"
        )

    baseline = anomaly.baseline_evidence
    evidence: dict[str, Any] = {
        "adapter_version": ADAPTER_VERSION,
        "correlation_candidate": candidate.model_dump(mode="json"),
        "historical_unusualness": {
            "method": anomaly.detector_reason,
            "detector_rule_version": anomaly.detector_rule_version,
            "baseline_p95": baseline.statistics.p95,
            "baseline_version_id": baseline.version.baseline_version_id,
            "baseline_content_sha256": baseline.version.content_sha256,
            "exact_rarity_available": False,
            "p95_is_health_or_severity_threshold": False,
        },
        "location_semantics": {
            "kind": "monitoring_station",
            "coordinates_are_emission_source": False,
            "coordinates_confirm_exposure": False,
        },
    }
    if detection_evidence is not None:
        evidence["detection_result"] = detection_evidence

    return CellSignal(
        cell_id=cell_id,
        observed_at=anomaly.observed_at,
        hazard=AIR_POLLUTION,
        variable=anomaly.pollutant,
        value=anomaly.value,
        unit=anomaly.unit,
        source=anomaly.provider,
        # The detector proves only that the value exceeds historical p95. It
        # does not provide an exact percentile on the Coordinator's 0..1
        # rarity scale, so numeric rarity would be fabricated precision.
        rarity=None,
        direction=HIGH,
        baseline=None,
        location=CellLocation(
            latitude=latitude,
            longitude=longitude,
            precision_m=0.0,
            method="monitoring_station_coordinate",
        ),
        # The anomaly contract deliberately assigns neither confidence nor
        # health/emergency severity. Preserve those unknowns across the seam.
        confidence=None,
        severity=None,
        evidence=evidence,
    )
