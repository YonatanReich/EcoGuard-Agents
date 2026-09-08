"""Offline runtime-transport tests for the EA-308 -> EA-313 boundary."""

from datetime import datetime, timedelta, timezone

from agents.air_pollution_anomaly_schemas import AirPollutionAnomaly
from agents.air_pollution_correlation import correlation_candidate
from agents.air_pollution_response_schemas import AirPollutionResponsePlan
from agents.air_pollution_spatial_schemas import (
    PollutionSpatialContext,
    SpatiallyEnrichedAirPollutionAnomaly,
)
from backend.air_pollution_event_adapter import attach_air_pollution_state
from services.air_pollution_event_store import (
    InMemoryAirPollutionEventStore,
    StoredAirPollutionEvent,
)
from services.air_pollution_runtime_service import AirPollutionRuntimeService
from services.air_quality_schemas import (
    AirQualityCollectionResult,
    AirQualityMonitor,
    AirQualityObservation,
    AirQualityStation,
    StationCollectionResult,
)


NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
LOCATION = {"latitude": 32.1, "longitude": 34.8}
UNIT = "\u00b5g/m\u00b3"


def observation(*, minutes: int = 0, value: float = 42.0) -> AirQualityObservation:
    observed = NOW + timedelta(minutes=minutes)
    return AirQualityObservation(
        provider_station_id="station-1",
        provider_channel_id="channel-1",
        pollutant="PM2.5",
        provider_pollutant_id="provider-pm25",
        value=value,
        unit=UNIT,
        provider_unit="ug/m3",
        location=LOCATION,
        observed_at=observed,
        provider_timestamp=observed.isoformat(),
        provider_status="Valid",
    )


def station() -> AirQualityStation:
    return AirQualityStation(
        provider_station_id="station-1",
        name="Verified station name",
        location=LOCATION,
        active=True,
        monitors=[
            AirQualityMonitor(
                provider_channel_id="channel-1",
                pollutant="PM2.5",
                provider_pollutant_id="provider-pm25",
                unit=UNIT,
                provider_unit="ug/m3",
                active=True,
            )
        ],
    )


def anomaly(identifier: str = "pollution-1", *, observed_at: datetime = NOW) -> AirPollutionAnomaly:
    return AirPollutionAnomaly(
        detection_id=identifier,
        observed_at=observed_at,
        detected_at=NOW,
        location=LOCATION,
        pollutant_observations=[
            {
                "pollutant": "PM2.5",
                "value": 42.0,
                "unit": UNIT,
                "provider_unit": "ug/m3",
                "observed_at": observed_at,
                "source_id": "ministry",
            }
        ],
        severity="medium",
        confidence=0.64,
        explanation="Sustained PM2.5 anomaly from normalized observations.",
        anomaly_reasons=["sustained PM2.5 elevation"],
        sources=[
            {
                "source_id": "ministry",
                "source_name": "Israeli Ministry monitoring network",
                "metadata": {"station_id": "station-1", "channel_id": "channel-1"},
            }
        ],
    )


def stored_event(
    value: AirPollutionAnomaly | None = None,
    *,
    context: PollutionSpatialContext | None = None,
    status: str | None = None,
) -> StoredAirPollutionEvent:
    candidate = correlation_candidate(
        SpatiallyEnrichedAirPollutionAnomaly(anomaly=value or anomaly(), spatial_context=context)
        if context is not None
        else value or anomaly()
    )
    plan = None if status is None else (
        AirPollutionResponsePlan(
            status="failed",
            reason="guidance_unavailable",
            limitations=["No applicable verified guidance was available."],
        )
        if status == "failed"
        else AirPollutionResponsePlan(
            status="skipped",
            reason="insufficient_anomaly_evidence",
            limitations=["Evidence was insufficient for planning."],
        )
    )
    return StoredAirPollutionEvent(event=candidate, plan=plan)


class FakeClient:
    def __init__(self, observations=None, *, failed=False):
        self.observations = list(observations or [])
        self.failed = failed
        self.station_calls = 0
        self.collection_calls = 0

    def get_station_metadata(self):
        self.station_calls += 1
        return StationCollectionResult(status="success", stations=[station()])

    def collect_latest(self):
        self.collection_calls += 1
        return AirQualityCollectionResult(
            status="failed" if self.failed else "success",
            collected_at=NOW,
            observations=[] if self.failed else self.observations,
            errors=["provider_timeout"] if self.failed else [],
        )


class FakeDetector:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def detect(self, request, *, detected_at):
        self.calls.append((request, detected_at))
        return self.outputs.pop(0) if self.outputs else None


class FakeEnricher:
    def __init__(self):
        self.calls = []

    def enrich(self, event):
        self.calls.append(event)
        return SpatiallyEnrichedAirPollutionAnomaly(
            anomaly=event,
            spatial_context=PollutionSpatialContext(
                location=event.location,
                lookup_radius_km=2.0,
                status="success",
                source="OpenStreetMap via existing geospatial agent",
                collected_at=NOW,
                provider_collection_status="success",
                nearby_settlements=[
                    {
                        "name": "Nearby place",
                        "osm_id": 7,
                        "osm_type": "node",
                        "latitude": 32.11,
                        "longitude": 34.81,
                    }
                ],
            ),
        )


def runtime(*, client, detector, store=None, enricher=None):
    return AirPollutionRuntimeService(
        store=store or InMemoryAirPollutionEventStore(),
        client=client,
        detector=detector,
        enricher=enricher or FakeEnricher(),
        cadence_minutes=5,
        clock=lambda: NOW,
    )


def base_fire_response(events=None):
    return {
        "metadata": {
            "timestamp": NOW.isoformat(),
            "collection_status": "success",
            "services": {"detection": {"status": "success", "source": "NASA FIRMS"}},
        },
        "query": {"latitude": 32.1, "longitude": 34.8},
        "events": list(events or []),
    }


def test_no_anomaly_stores_no_event_and_skips_downstream_work():
    client = FakeClient([observation()])
    detector = FakeDetector([None])
    enricher = FakeEnricher()
    service = runtime(client=client, detector=detector, enricher=enricher)

    result = service.refresh()

    assert result["status"] == "success"
    assert service.store.snapshot().events == []
    assert len(detector.calls) == 1
    assert enricher.calls == []


def test_refresh_supplies_only_sufficient_prior_history_as_robust_baseline():
    store = InMemoryAirPollutionEventStore()
    store.append_observations([
        observation(minutes=-5 * offset, value=10.0 + (offset % 3))
        for offset in range(20, 0, -1)
    ])
    detector = FakeDetector([None])
    service = runtime(
        store=store,
        client=FakeClient([observation()]),
        detector=detector,
    )

    service.refresh()
    request = detector.calls[0][0]

    assert request.historical_baseline is not None
    assert len(request.historical_baseline.values) == 20
    assert request.historical_baseline.ended_at < NOW
    assert request.historical_baseline.version == "runtime-robust-baseline-v1"


def test_valid_anomaly_preserves_spatial_context_without_precoordinator_plan():
    service = runtime(client=FakeClient([observation()]), detector=FakeDetector([anomaly()]))

    service.refresh()
    stored = service.store.snapshot().events[0]
    payload = attach_air_pollution_state(base_fire_response(), service.store.snapshot())
    event = payload["events"][0]

    assert stored.event.spatial_context.nearby_settlements[0].name == "Nearby place"
    assert event["type"] == "air_pollution"
    assert event["anomaly"]["detection_id"] == "pollution-1"
    assert event["spatial_context"]["nearby_settlements"][0]["osm_id"] == 7
    assert "pollution_response_plan" not in event
    assert "planning_status" not in event
    assert "allocated_resources" not in event


def test_grounded_response_plan_is_preserved_by_the_transport_adapter():
    candidate = correlation_candidate(anomaly())
    result = StoredAirPollutionEvent(
        event=candidate,
        plan=AirPollutionResponsePlan(
            status="success",
            summary="Continue authoritative monitoring and publish reviewed updates.",
            recommended_authority_types=["environmental_protection_authority"],
            recommended_resource_types=["air_quality_monitoring"],
            actions=[{
                "recommendation": "Continue authoritative monitoring and publish reviewed updates.",
                "responsible_authority_type": "environmental_protection_authority",
                "resource_type": "air_quality_monitoring",
                "timeframe": "ongoing",
                "priority": "monitoring",
                "supporting_chunk_ids": ["pollution-guidance#monitoring#0"],
            }],
            protocol_references=[{
                "chunk_id": "pollution-guidance#monitoring#0",
                "document_id": "pollution-guidance",
                "document_title": "Reviewed pollution guidance",
                "source_url": "https://example.invalid/reviewed-pollution-guidance",
                "heading_path": "Monitoring",
                "quoted_text": "Continue authoritative monitoring and publish reviewed updates.",
                "supports": "Monitoring and public information",
                "verified": True,
            }],
        ),
    )
    store = InMemoryAirPollutionEventStore()
    store.replace_events(
        [result], status="success", attempted_at=NOW,
        collected_at=NOW, observation_count=1, excluded_count=0, errors=[],
    )

    event = attach_air_pollution_state(base_fire_response(), store.snapshot())["events"][0]

    assert event["pollution_response_plan"]["status"] == "success"
    assert event["pollution_response_plan"]["protocol_references"][0]["verified"] is True


def test_downstream_fail_closed_plan_does_not_hide_the_anomaly():
    store = InMemoryAirPollutionEventStore()
    store.replace_events(
        [stored_event(status="failed")],
        status="success",
        attempted_at=NOW,
        collected_at=NOW,
        observation_count=1,
        excluded_count=0,
        errors=[],
    )

    event = attach_air_pollution_state(base_fire_response(), store.snapshot())["events"][0]

    assert event["anomaly"]["detection_id"] == "pollution-1"
    assert event["pollution_response_plan"]["status"] == "failed"
    assert event["pollution_response_plan"]["reason"] == "guidance_unavailable"


def test_prior_candidate_produces_real_correlation_evidence_without_deduplication():
    store = InMemoryAirPollutionEventStore()
    earlier = anomaly("pollution-earlier", observed_at=NOW - timedelta(minutes=5))
    store.replace_events(
        [stored_event(earlier)],
        status="success",
        attempted_at=NOW - timedelta(minutes=5),
        collected_at=NOW - timedelta(minutes=5),
        observation_count=1,
        excluded_count=0,
        errors=[],
    )
    service = runtime(
        store=store,
        client=FakeClient([observation()]),
        detector=FakeDetector([anomaly("pollution-current")]),
    )

    service.refresh()
    result = store.snapshot().events[0]

    assert result.correlation_evidence is not None
    assert result.correlation_evidence.candidate_match is True
    assert "within_time_window" in result.correlation_evidence.matching_signals
    assert result.event.anomaly.detection_id == "pollution-current"


def test_provider_failure_retains_prior_event_as_stale_without_fabrication():
    store = InMemoryAirPollutionEventStore()
    store.replace_events(
        [stored_event()], status="success", attempted_at=NOW - timedelta(minutes=5),
        collected_at=NOW - timedelta(minutes=5),
        observation_count=1, excluded_count=0, errors=[],
    )
    service = runtime(store=store, client=FakeClient(failed=True), detector=FakeDetector([]))

    service.refresh()
    snapshot = store.snapshot()

    assert snapshot.status == "failed" and snapshot.stale is True
    assert len(snapshot.events) == 1
    assert snapshot.errors == ["provider_timeout"]
    event = attach_air_pollution_state(base_fire_response(), snapshot)["events"][0]
    assert event["air_pollution_runtime"]["stale"] is True


def test_provider_failure_without_prior_state_adds_no_fake_event_and_keeps_fire():
    store = InMemoryAirPollutionEventStore()
    service = runtime(store=store, client=FakeClient(failed=True), detector=FakeDetector([]))
    service.refresh()
    fire = {"id": "fire-1", "type": "fire", "latitude": 31.9, "longitude": 34.8}

    response = attach_air_pollution_state(base_fire_response([fire]), store.snapshot())

    assert response["events"] == [fire]
    assert response["metadata"]["services"]["air_pollution"]["status"] == "failed"
    assert response["metadata"]["collection_status"] == "partial_service_failure"


def test_fire_and_pollution_coexist_and_fire_only_shape_remains_compatible():
    fire = {"id": "fire-1", "type": "fire", "latitude": 31.9, "longitude": 34.8}
    store = InMemoryAirPollutionEventStore()
    store.replace_events(
        [stored_event()], status="success", attempted_at=NOW,
        collected_at=NOW, observation_count=1, excluded_count=0, errors=[],
    )

    combined = attach_air_pollution_state(base_fire_response([fire]), store.snapshot())
    untouched = attach_air_pollution_state(
        base_fire_response([fire]), InMemoryAirPollutionEventStore().snapshot(),
    )

    assert [item["type"] for item in combined["events"]] == ["fire", "air_pollution"]
    assert untouched["events"] == [fire]
    assert "air_pollution" in untouched["metadata"]["services"]


def test_multiple_pollution_candidates_are_preserved_with_stable_detection_ids():
    store = InMemoryAirPollutionEventStore()
    second_payload = anomaly("pollution-2").model_dump()
    second_payload["location"] = {"latitude": 32.2, "longitude": 34.9}
    second = AirPollutionAnomaly.model_validate(second_payload)
    store.replace_events(
        [stored_event(anomaly("pollution-1")), stored_event(second)],
        status="success", attempted_at=NOW, collected_at=NOW,
        observation_count=2, excluded_count=0, errors=[],
    )

    response = attach_air_pollution_state(base_fire_response(), store.snapshot())

    assert [event["id"] for event in response["events"]] == ["pollution-1", "pollution-2"]
    assert [(event["latitude"], event["longitude"]) for event in response["events"]] == [
        (32.1, 34.8),
        (32.2, 34.9),
    ]


def test_failed_fire_envelope_does_not_erase_stored_pollution_candidates():
    store = InMemoryAirPollutionEventStore()
    store.replace_events(
        [stored_event()], status="success", attempted_at=NOW,
        collected_at=NOW, observation_count=1, excluded_count=0, errors=[],
    )
    failed_fire = base_fire_response()
    failed_fire["metadata"]["collection_status"] = "failed"
    failed_fire["metadata"]["services"]["detection"]["status"] = "failed"

    response = attach_air_pollution_state(failed_fire, store.snapshot())

    assert [event["id"] for event in response["events"]] == ["pollution-1"]
    assert response["metadata"]["collection_status"] == "partial_service_failure"


def test_repeated_api_reads_do_not_run_pollution_refresh(monkeypatch):
    from backend import main

    refresh_calls = []
    monkeypatch.setattr(main.air_pollution_runtime, "refresh", lambda: refresh_calls.append(True))
    monkeypatch.setattr(
        main.fire_coordinator,
        "run_event_pipeline",
        lambda *args, **kwargs: {
            "status": "no_event",
            "detection": {
                "detected": False,
                "metadata": {"collection_status": "success", "timestamp": NOW.isoformat()},
            },
            "risk_analysis": {"metadata": {"analysis_status": "skipped"}},
            "planning": {"metadata": {"planning_status": "skipped"}},
            "allocated_resources": {"status": "skipped"},
        },
    )

    for _ in range(2):
        main.get_detected_events(
            latitude=32.1, longitude=34.8, radius_km=5.0,
            day_range=2, include_analysis=False,
        )

    assert refresh_calls == []


def test_detected_events_endpoint_returns_fire_and_stored_pollution(monkeypatch):
    from backend import main

    store = InMemoryAirPollutionEventStore()
    store.replace_events(
        [stored_event()], status="success", attempted_at=NOW,
        collected_at=NOW, observation_count=1, excluded_count=0, errors=[],
    )
    monkeypatch.setattr(main, "air_pollution_event_store", store)
    monkeypatch.setattr(
        main.fire_coordinator,
        "run_event_pipeline",
        lambda *args, **kwargs: {
            "status": "success",
            "location": LOCATION,
            "detection": {
                "detected": True,
                "event_type": "fire",
                "location": LOCATION,
                "metadata": {
                    "collection_status": "success",
                    "timestamp": NOW.isoformat(),
                },
            },
            "risk_analysis": {
                "metadata": {"analysis_status": "skipped"},
                "grounding": {"citations": []},
            },
            "planning": {
                "metadata": {"planning_status": "skipped"},
                "grounding": {"citations": []},
                "response_actions": [],
            },
            "allocated_resources": {"status": "skipped"},
        },
    )

    response = main.get_detected_events(
        latitude=32.1, longitude=34.8, radius_km=5.0,
        day_range=2, include_analysis=False,
    )

    assert [event["type"] for event in response["events"]] == ["fire", "air_pollution"]


def test_runtime_accepts_a_store_implementation_through_the_protocol():
    class DelegatingStore:
        def __init__(self):
            self.inner = InMemoryAirPollutionEventStore()

        def snapshot(self): return self.inner.snapshot()
        def append_observations(self, values): return self.inner.append_observations(values)
        def observation_series(self, value): return self.inner.observation_series(value)
        def replace_events(self, values, **kwargs): return self.inner.replace_events(values, **kwargs)
        def record_failure(self, **kwargs): return self.inner.record_failure(**kwargs)

    store = DelegatingStore()
    service = runtime(
        store=store,
        client=FakeClient([observation()]),
        detector=FakeDetector([None]),
    )

    service.refresh()

    assert store.snapshot().status == "success"
