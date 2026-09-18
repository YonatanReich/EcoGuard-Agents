from datetime import date, datetime, timezone

import pytest

from ecoguard.coordinator import agent as coordinator
from ecoguard.coordinator.queues import NON_EMERGENCY, queue_for
from ecoguard.detectors.air_pollution.baseline_schemas import (
    BaselineBucketStatistics,
    BaselineIdentity,
    BaselineVersionProvenance,
    LiveObservationContext,
)
from ecoguard.detectors.air_pollution.cell_signal_adapter import (
    AirPollutionCellSignalAdapterError,
    air_pollution_candidate_to_cell_signal,
    air_pollution_detection_to_cell_signal,
)
from ecoguard.detectors.air_pollution.correlation import PollutionCorrelationCandidate
from ecoguard.detectors.air_pollution.schemas import (
    AirPollutionAnomaly,
    AirPollutionBaselineEvidence,
    AirPollutionDetectionResult,
)
from ecoguard.detectors.air_pollution.spatial_schemas import PollutionSpatialContext
from ecoguard.shared.cells import cell_for
from ecoguard.shared.signals import AIR_POLLUTION, CellSignal

OBSERVED_AT = datetime(2026, 9, 13, 17, 15, tzinfo=timezone.utc)
PROVIDER = "israel_ministry_environment_air_monitoring"


def _anomaly(*, latitude: float = 32.1, longitude: float = 34.8) -> AirPollutionAnomaly:
    location = {"latitude": latitude, "longitude": longitude}
    live = LiveObservationContext(
        provider=PROVIDER,
        station_id="42",
        channel_id="7001",
        pollutant="NO2",
        value=21.0,
        observed_at=OBSERVED_AT,
        provider_timestamp="2026-09-13 20:15:00",
        measurement_unit="ppb",
        unit_source="reading",
        reading_unit="ppb",
        location=location,
    )
    baseline = AirPollutionBaselineEvidence(
        identity=BaselineIdentity(
            provider=PROVIDER,
            station_id="42",
            channel_id="7001",
            pollutant="NO2",
            canonical_unit="ppb",
            baseline_family="five_minute_observation",
        ),
        month=9,
        hour=20,
        statistics=BaselineBucketStatistics(
            status="ok",
            sample_count=150,
            distinct_days=100,
            distinct_years=5,
            years_present=[2021, 2022, 2023, 2024, 2025],
            mean=8.0,
            median=7.0,
            std=3.0,
            mad=1.5,
            p05=2.0,
            p25=4.0,
            p75=12.0,
            p95=20.0,
        ),
        version=BaselineVersionProvenance(
            baseline_version_id=77,
            content_sha256="a" * 64,
            coverage_status="FULL_BASELINE",
            lifecycle_status="active",
            schema_version="air-pollution-baseline-profile-v2",
            method_version="national-v2-five-minute",
            source_name="Israeli Ministry / Envista",
            source_version="2021-2025",
            training_start=date(2021, 1, 1),
            training_end=date(2025, 12, 31),
            imported_at=OBSERVED_AT,
            generated_at=OBSERVED_AT,
            aggregation_policy_version="provider-five-minute-month-hour-v1",
            quality_policy_version="ecoguard-provider-valid-signed-v1",
            source_metadata={"official": True},
            aggregation_metadata={},
            quality_metadata={"signed_values": "preserved"},
            coverage_metadata={},
        ),
    )
    return AirPollutionAnomaly(
        detection_id="air-pollution:test-a",
        observed_at=OBSERVED_AT,
        detected_at=OBSERVED_AT,
        location=location,
        provider=PROVIDER,
        station_id="42",
        station_name="Central Station",
        channel_id="7001",
        pollutant="NO2",
        value=21.0,
        unit="ppb",
        live_observation=live,
        detector_reason="live_value_above_baseline_p95",
        detector_rule_version="air-pollution-five-minute-p95-v1",
        baseline_evidence=baseline,
    )


def _detection(anomaly: AirPollutionAnomaly | None = None) -> AirPollutionDetectionResult:
    anomaly = anomaly or _anomaly()
    return AirPollutionDetectionResult(
        status="SUSPECTED_ANOMALY",
        reason="live_value_above_baseline_p95",
        detector_rule_version=anomaly.detector_rule_version,
        live_observation=anomaly.live_observation,
        baseline_evidence=anomaly.baseline_evidence,
        anomaly=anomaly,
    )


def test_qualified_detection_maps_to_canonical_advisory_signal():
    anomaly = _anomaly()
    signal = air_pollution_detection_to_cell_signal(_detection(anomaly))

    assert isinstance(signal, CellSignal)
    assert signal.hazard == AIR_POLLUTION == "air_pollution"
    assert queue_for(signal.hazard) == NON_EMERGENCY
    assert signal.cell_id == cell_for(
        anomaly.location.latitude, anomaly.location.longitude
    )
    assert signal.location.latitude == anomaly.location.latitude
    assert signal.location.longitude == anomaly.location.longitude
    assert signal.location.method == "monitoring_station_coordinate"
    assert signal.evidence["detection_result"]["status"] == "SUSPECTED_ANOMALY"


def test_signal_preserves_anomaly_baseline_and_spatial_evidence():
    anomaly = _anomaly()
    spatial = PollutionSpatialContext(
        location=anomaly.location,
        lookup_radius_km=2.0,
        status="partial",
        source="OpenStreetMap / Overpass API",
        collected_at=OBSERVED_AT,
        missing_layers=["nearby_hospitals"],
        limitations=["Context does not establish pollution origin."],
    )
    signal = air_pollution_candidate_to_cell_signal(
        PollutionCorrelationCandidate(anomaly=anomaly, spatial_context=spatial)
    )

    retained = signal.evidence["correlation_candidate"]
    retained_anomaly = retained["anomaly"]
    assert retained_anomaly["station_id"] == "42"
    assert retained_anomaly["channel_id"] == "7001"
    assert retained_anomaly["pollutant"] == "NO2"
    assert retained_anomaly["unit"] == "ppb"
    assert retained_anomaly["value"] == 21.0
    assert retained_anomaly["observed_at"] == OBSERVED_AT.isoformat().replace(
        "+00:00", "Z"
    )
    assert retained_anomaly["baseline_evidence"]["statistics"]["p95"] == 20.0
    assert (
        retained_anomaly["baseline_evidence"]["version"]["content_sha256"]
        == "a" * 64
    )
    assert retained["spatial_context"]["missing_layers"] == ["nearby_hospitals"]


def test_p95_qualification_is_not_fabricated_as_rarity_or_severity():
    signal = air_pollution_detection_to_cell_signal(_detection())

    assert signal.rarity is None
    assert signal.baseline is None
    assert signal.severity is None
    assert signal.confidence is None
    assert signal.reportable is False
    unusualness = signal.evidence["historical_unusualness"]
    assert unusualness["baseline_p95"] == 20.0
    assert unusualness["exact_rarity_available"] is False
    assert unusualness["p95_is_health_or_severity_threshold"] is False
    assert signal.evidence["location_semantics"] == {
        "kind": "monitoring_station",
        "coordinates_are_emission_source": False,
        "coordinates_confirm_exposure": False,
    }


def test_non_anomaly_detection_fails_closed():
    detection = AirPollutionDetectionResult(
        status="NORMAL",
        reason="live_value_at_or_below_baseline_p95",
        detector_rule_version="air-pollution-five-minute-p95-v1",
    )

    with pytest.raises(
        AirPollutionCellSignalAdapterError, match="detection_not_qualified"
    ):
        air_pollution_detection_to_cell_signal(detection)


def test_unvalidated_input_fails_closed():
    with pytest.raises(
        AirPollutionCellSignalAdapterError, match="invalid_detection_result"
    ):
        air_pollution_detection_to_cell_signal({"status": "SUSPECTED_ANOMALY"})


def test_station_outside_shared_service_area_fails_closed():
    with pytest.raises(
        AirPollutionCellSignalAdapterError,
        match="monitoring_station_outside_service_area",
    ):
        air_pollution_detection_to_cell_signal(
            _detection(_anomaly(latitude=0.0, longitude=0.0))
        )


def test_signal_is_accepted_by_current_coordinator_contract(monkeypatch):
    signal = air_pollution_detection_to_cell_signal(_detection())
    incidents = []

    monkeypatch.setattr(coordinator.store, "close_quiet", lambda *_: [])
    monkeypatch.setattr(coordinator.store, "next_incident_id", lambda _: "INC-TEST-1")

    def open_incidents(hazards=None):
        if hazards is None:
            return list(incidents)
        return [item for item in incidents if set(item["hazards"]) & set(hazards)]

    def create_incident(incident_id, supplied, queues):
        incidents.append(
            {
                "id": incident_id,
                "status": "open",
                "primary_hazard": supplied.hazard,
                "hazards": [supplied.hazard],
                "queues": list(queues),
                "cells": [supplied.cell_id],
                "last_signal_at": supplied.observed_at,
            }
        )

    monkeypatch.setattr(coordinator.store, "open_incidents", open_incidents)
    monkeypatch.setattr(coordinator.store, "create_incident", create_incident)
    monkeypatch.setattr(coordinator, "_package", lambda _: [])

    result = coordinator.coordinate([signal], at=OBSERVED_AT)

    assert result.created == ["INC-TEST-1"]
    assert result.emergency == []
    assert [item["id"] for item in result.non_emergency] == ["INC-TEST-1"]
