"""Focused tests for the IMS HTTP and WindEvidence adapter boundary."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import pytest
import requests
from pydantic import ValidationError

from agents.air_pollution_anomaly_schemas import GeographicCoordinate
from agents.air_pollution_transport_schemas import WindEvidence
from services.ims_wind_evidence_service import (
    IMSWindEvidenceError,
    IMSWindEvidenceService,
    normalize_ims_observation_timestamp,
    normalize_ims_wind_observation,
    parse_ims_station_metadata,
    parse_ims_wind_observations,
)
from services.ims_wind_observation_client import (
    IMS_API_ROOT,
    IMSHTTPDiagnostic,
    IMSWindObservationClient,
    IMSWindObservationError,
)


ANOMALY_TIME = datetime(2026, 7, 1, 10, 30, tzinfo=timezone.utc)
RETRIEVED_AT = datetime(2026, 7, 1, 10, 31, tzinfo=timezone.utc)
ORIGIN = GeographicCoordinate(latitude=32.0, longitude=34.8)


def monitor(
    name: str,
    channel_id: int,
    *,
    active: bool = True,
    units: str | None = None,
) -> dict[str, Any]:
    return {
        "active": active,
        "channelId": channel_id,
        "name": name,
        "typeId": channel_id + 100,
        "units": units or ("m/sec" if name in {"WS", "WSmax"} else "deg"),
    }


def station(
    station_id: int,
    *,
    latitude: float = 32.01,
    longitude: float = 34.8,
    active: bool = True,
    monitors: list[dict[str, Any]] | None = None,
    timebase: int | None = 10,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stationId": station_id,
        "name": f"Station {station_id}",
        "active": active,
        "location": {"latitude": latitude, "longitude": longitude},
        "regionId": 7,
        "regionName": "Coastal plain",
        "monitors": monitors
        if monitors is not None
        else [monitor("WD", station_id * 10 + 1), monitor("WS", station_id * 10 + 2)],
    }
    if timebase is not None:
        payload["timebase"] = timebase
    return payload


def reading(
    channel_id: int,
    name: str,
    value: float,
    *,
    valid: bool = True,
    status: object = 1,
) -> dict[str, Any]:
    return {
        "id": channel_id,
        "name": name,
        "value": value,
        "valid": valid,
        "status": status,
    }


def observation(
    station_id: int,
    *,
    timestamp: str = "2026-07-01T12:20:00+03:00",
    wd: float = 270.0,
    ws: float = 4.0,
    wd_id: int | None = None,
    ws_id: int | None = None,
    extra: list[dict[str, Any]] | None = None,
    wd_valid: bool = True,
    ws_valid: bool = True,
    wd_status: object = 1,
    ws_status: object = 1,
) -> dict[str, Any]:
    return {
        "datetime": timestamp,
        "channels": [
            reading(wd_id or station_id * 10 + 1, "WD", wd, valid=wd_valid, status=wd_status),
            reading(ws_id or station_id * 10 + 2, "WS", ws, valid=ws_valid, status=ws_status),
            *(extra or []),
        ],
    }


class FakeIMSClient:
    def __init__(
        self,
        stations: list[dict[str, Any]],
        observations: dict[str, object],
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self.station_payload = stations
        self.observations = observations
        self.details = details or {}
        self.range_calls: list[tuple[str, date, date]] = []
        self.daily_calls: list[tuple[str, date]] = []

    def get_stations(self) -> object:
        return self.station_payload

    def get_station(self, station_id: object) -> object:
        return self.details[str(station_id)]

    def get_station_data_range(
        self, station_id: object, start_date: date, end_date: date
    ) -> object:
        key = str(station_id)
        self.range_calls.append((key, start_date, end_date))
        return self.observations[key]

    def get_station_data_daily(self, station_id: object, day: date) -> object:
        key = str(station_id)
        self.daily_calls.append((key, day))
        result = self.observations[key]
        if isinstance(result, Exception):
            raise result
        return result

    @staticmethod
    def station_data_reference(station_id: object) -> str:
        return f"{IMS_API_ROOT}/stations/{station_id}/data"


def service_for(
    stations: list[dict[str, Any]], observations: dict[str, object]
) -> IMSWindEvidenceService:
    return IMSWindEvidenceService(
        FakeIMSClient(stations, observations),  # type: ignore[arg-type]
        clock=lambda: RETRIEVED_AT,
    )


def select(
    stations: list[dict[str, Any]],
    observations: dict[str, object],
    **kwargs: Any,
):
    return service_for(stations, observations).select_wind_evidence(
        analysis_coordinates=ORIGIN,
        anomaly_observed_at=ANOMALY_TIME,
        maximum_observation_age_seconds=3600.0,
        **kwargs,
    )


def test_station_metadata_parses_location_region_timebase_and_named_channels():
    raw = station(
        17,
        monitors=[
            monitor("WD", 101),
            monitor("WS", 204),
            monitor("STDwd", 305),
            monitor("WDmax", 406),
            monitor("WSmax", 507),
            monitor("TD", 999),
        ],
    )

    parsed = parse_ims_station_metadata(raw)

    assert parsed.station_id == "17"
    assert parsed.region_id == "7"
    assert parsed.region_name == "Coastal plain"
    assert parsed.coordinates == GeographicCoordinate(latitude=32.01, longitude=34.8)
    assert parsed.timebase_minutes == 10
    assert [item.name for item in parsed.channels] == [
        "WD",
        "WS",
        "STDwd",
        "WDmax",
        "WSmax",
    ]
    assert parsed.wind_capable is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.update(active=False),
        lambda raw: raw.update(monitors=[monitor("WS", 12)]),
        lambda raw: raw.update(monitors=[monitor("WD", 11)]),
        lambda raw: raw.update(monitors=[monitor("WD", 11, active=False), monitor("WS", 12)]),
    ],
    ids=["inactive-station", "missing-wd", "missing-ws", "inactive-wd"],
)
def test_inactive_or_non_wind_capable_station_is_rejected(mutation):
    raw = station(1)
    mutation(raw)

    with pytest.raises(IMSWindEvidenceError, match="no_eligible_wind_observation"):
        select([raw], {"1": [observation(1)]})


def test_optional_stddev_and_gust_channels_are_discovered_and_normalized():
    raw_station = station(
        1,
        monitors=[
            monitor("WD", 41),
            monitor("WS", 57),
            monitor("STDwd", 73),
            monitor("WDmax", 88),
            monitor("WSmax", 99),
        ],
    )
    raw_observation = observation(
        1,
        wd_id=41,
        ws_id=57,
        extra=[
            reading(73, "STDwd", 14.5),
            reading(88, "WDmax", 295.0),
            reading(99, "WSmax", 8.25),
        ],
    )

    evidence = select([raw_station], {"1": [raw_observation]}).wind_evidence

    assert evidence.direction_stddev_deg == 14.5
    assert evidence.gust_from_direction_deg == 295.0
    assert evidence.gust_speed_mps == 8.25
    assert evidence.original_units.direction_stddev == "deg"
    assert evidence.provider_channel_validity["STDwd"] == "valid"


def test_missing_optional_channels_remain_null_without_imputation():
    evidence = select([station(1)], {"1": [observation(1)]}).wind_evidence

    assert evidence.direction_stddev_deg is None
    assert evidence.gust_from_direction_deg is None
    assert evidence.gust_speed_mps is None
    assert evidence.original_units.direction_stddev is None
    assert evidence.provider_channel_validity["STDwd"] == "unknown"


def test_station_specific_channel_ids_are_not_hardcoded():
    station_one = station(1, latitude=32.2)
    station_two = station(
        2,
        latitude=32.01,
        monitors=[monitor("WD", 901), monitor("WS", 777)],
    )
    result = select(
        [station_one, station_two],
        {
            "1": [observation(1)],
            "2": [observation(2, wd_id=901, ws_id=777, wd=180.0, ws=5.0)],
        },
    )

    assert result.wind_evidence.provider_location_id == "2"
    assert result.wind_evidence.wind_from_direction_deg == 180.0


def test_station_summary_without_monitors_uses_station_detail_metadata():
    summary = station(1)
    summary.pop("monitors")
    detailed = station(1, monitors=[monitor("WD", 501), monitor("WS", 909)])
    client = FakeIMSClient(
        [summary],
        {"1": [observation(1, wd_id=501, ws_id=909)]},
        details={"1": detailed},
    )
    service = IMSWindEvidenceService(client, clock=lambda: RETRIEVED_AT)  # type: ignore[arg-type]

    result = service.select_wind_evidence(
        analysis_coordinates=ORIGIN,
        anomaly_observed_at=ANOMALY_TIME,
        maximum_observation_age_seconds=3600.0,
    )

    assert result.wind_evidence.provider_location_id == "1"


def test_one_station_with_empty_data_does_not_hide_another_valid_station():
    result = select(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {"1": [], "2": [observation(2)]},
    )

    assert result.wind_evidence.provider_location_id == "2"


def station_error(category: str) -> IMSWindObservationError:
    return IMSWindObservationError(
        category,
        transient=category in {"timeout", "network_error", "provider_http_error"},
    )


def test_first_station_204_is_skipped_and_second_station_succeeds():
    client = FakeIMSClient(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {"1": station_error("empty_response"), "2": [observation(2)]},
    )
    service = IMSWindEvidenceService(client, clock=lambda: RETRIEVED_AT)  # type: ignore[arg-type]

    result = service.select_wind_evidence(
        analysis_coordinates=ORIGIN,
        anomaly_observed_at=ANOMALY_TIME,
        maximum_observation_age_seconds=3600.0,
    )

    assert result.wind_evidence.provider_location_id == "2"
    assert result.diagnostics.station_days_without_data == 1
    assert result.diagnostics.stations_skipped_no_daily_data == 1
    assert client.daily_calls == [
        ("1", date(2026, 7, 1)),
        ("2", date(2026, 7, 1)),
    ]


def test_middle_station_204_does_not_prevent_later_valid_selection():
    result = select(
        [
            station(1, latitude=32.001),
            station(2, latitude=32.01),
            station(3, latitude=32.02),
        ],
        {
            "1": [observation(1, timestamp="2026-07-01T11:00:00+03:00")],
            "2": station_error("empty_response"),
            "3": [observation(3)],
        },
    )

    assert result.wind_evidence.provider_location_id == "3"
    assert result.diagnostics.stations_skipped_stale == 1
    assert result.diagnostics.station_days_without_data == 1


def test_multiple_204_stations_are_skipped_before_valid_station():
    result = select(
        [station(1, latitude=32.001), station(2, latitude=32.01), station(3, latitude=32.02)],
        {
            "1": station_error("empty_response"),
            "2": station_error("empty_response"),
            "3": [observation(3)],
        },
    )

    assert result.wind_evidence.provider_location_id == "3"
    assert result.diagnostics.station_days_without_data == 2
    assert result.diagnostics.eligible_stations == 1


def test_all_204_stations_return_clean_no_eligible_result_with_counts():
    service = service_for(
        [station(1), station(2)],
        {"1": station_error("empty_response"), "2": station_error("empty_response")},
    )

    with pytest.raises(IMSWindEvidenceError, match="no_eligible_wind_observation") as error:
        service.select_wind_evidence(
            analysis_coordinates=ORIGIN,
            anomaly_observed_at=ANOMALY_TIME,
            maximum_observation_age_seconds=3600.0,
        )

    assert error.value.diagnostics["station_days_without_data"] == 2
    assert error.value.diagnostics["eligible_stations"] == 0


def test_json_without_required_wind_values_is_skipped_for_later_station():
    no_wind = {
        "datetime": "2026-07-01T12:20:00+03:00",
        "channels": [reading(999, "TD", 25.0)],
    }

    result = select(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {"1": [no_wind], "2": [observation(2)]},
    )

    assert result.wind_evidence.provider_location_id == "2"
    assert result.diagnostics.stations_skipped_invalid_wind_observation == 1


def test_invalid_required_wind_values_are_skipped_for_later_station():
    result = select(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {
            "1": [observation(1, wd_valid=False)],
            "2": [observation(2)],
        },
    )

    assert result.wind_evidence.provider_location_id == "2"
    assert result.diagnostics.stations_skipped_invalid_wind_observation == 1


def test_stale_station_is_skipped_for_later_valid_station():
    result = select(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {
            "1": [observation(1, timestamp="2026-07-01T11:00:00+03:00")],
            "2": [observation(2)],
        },
    )

    assert result.wind_evidence.provider_location_id == "2"
    assert result.diagnostics.stations_skipped_stale == 1


def test_future_only_station_is_skipped_for_later_valid_station():
    result = select(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {
            "1": [observation(1, timestamp="2026-07-01T13:00:00+03:00")],
            "2": [observation(2)],
        },
    )

    assert result.wind_evidence.provider_location_id == "2"
    assert result.diagnostics.stations_skipped_future_only == 1


def test_station_observation_404_is_local_no_data_and_selection_continues():
    result = select(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {"1": station_error("not_found"), "2": [observation(2)]},
    )

    assert result.wind_evidence.provider_location_id == "2"
    assert result.diagnostics.station_days_without_data == 1


@pytest.mark.parametrize(
    "category",
    ["authentication_failed", "network_error", "timeout", "provider_http_error"],
)
def test_provider_or_system_failures_remain_fatal_and_distinguishable(category):
    service = service_for(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {"1": station_error(category), "2": [observation(2)]},
    )

    with pytest.raises(IMSWindObservationError, match=category) as error:
        service.select_wind_evidence(
            analysis_coordinates=ORIGIN,
            anomaly_observed_at=ANOMALY_TIME,
            maximum_observation_age_seconds=3600.0,
        )

    assert error.value.category == category


def test_one_unusable_response_does_not_hide_later_valid_station():
    result = select(
        [station(1, latitude=32.001), station(2, latitude=32.02)],
        {"1": station_error("invalid_json"), "2": [observation(2)]},
    )

    assert result.wind_evidence.provider_location_id == "2"
    assert result.diagnostics.stations_skipped_unusable_response == 1


def test_unusable_responses_across_all_candidates_preserve_provider_error():
    service = service_for(
        [station(1), station(2)],
        {"1": station_error("invalid_json"), "2": station_error("invalid_json")},
    )

    with pytest.raises(IMSWindObservationError, match="invalid_json"):
        service.select_wind_evidence(
            analysis_coordinates=ORIGIN,
            anomaly_observed_at=ANOMALY_TIME,
            maximum_observation_age_seconds=3600.0,
        )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"wd_valid": False}, "no_eligible"),
        ({"ws_valid": False}, "no_eligible"),
        ({"wd_status": 2}, "no_eligible"),
        ({"ws_status": "invalid"}, "no_eligible"),
        ({"wd": -1.0}, "no_eligible"),
        ({"wd": 360.0}, "no_eligible"),
        ({"ws": -0.1}, "no_eligible"),
        ({"ws": float("nan")}, "no_eligible"),
        ({"ws": float("inf")}, "no_eligible"),
    ],
)
def test_invalid_required_observation_is_never_selected(changes, expected):
    with pytest.raises(IMSWindEvidenceError, match=expected):
        select([station(1)], {"1": [observation(1, **changes)]})


def test_speed_unit_is_normalized_while_original_units_are_preserved():
    raw_station = station(
        1,
        monitors=[monitor("WD", 11), monitor("WS", 12, units="km/h")],
    )

    evidence = select(
        [raw_station], {"1": [observation(1, ws=18.0)]}
    ).wind_evidence

    assert evidence.wind_speed_mps == pytest.approx(5.0)
    assert evidence.original_units.wind_speed == "km/h"


def test_selection_hard_filters_time_then_orders_by_distance_age_and_id():
    stations = [
        station(20, latitude=32.02),
        station(3, latitude=32.01),
        station(2, latitude=32.01),
    ]
    observations = {
        "20": [observation(20, timestamp="2026-07-01T12:29:00+03:00")],
        "3": [observation(3, timestamp="2026-07-01T12:10:00+03:00")],
        "2": [observation(2, timestamp="2026-07-01T12:10:00+03:00")],
    }

    result = select(stations, observations)

    assert result.wind_evidence.provider_location_id == "2"
    assert result.station_distance_m < result.eligible_alternatives[-1].station_distance_m
    assert [item.station_id for item in result.eligible_alternatives] == ["3", "20"]
    assert "distance, then observation age, then station ID" in " ".join(
        result.selection_rationale
    )


def test_most_recent_past_observation_is_used_and_future_is_never_selected():
    result = select(
        [station(1)],
        {
            "1": [
                observation(1, timestamp="2026-07-01T12:00:00+03:00", wd=100.0),
                observation(1, timestamp="2026-07-01T12:20:00+03:00", wd=200.0),
                observation(1, timestamp="2026-07-01T12:40:00+03:00", wd=300.0),
            ]
        },
    )

    assert result.wind_evidence.wind_from_direction_deg == 200.0
    assert result.wind_evidence.time_offset_from_anomaly_seconds == -600.0
    assert result.wind_evidence.metadata["look_ahead_used"] is False


def test_only_future_observation_is_safely_unavailable():
    with pytest.raises(IMSWindEvidenceError, match="no_eligible_wind_observation"):
        select(
            [station(1)],
            {"1": [observation(1, timestamp="2026-07-01T12:40:00+03:00")]},
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-07-01T12:20:00+03:00", "2026-07-01T10:20:00+00:00"),
        ("2026-01-01T12:20:00+03:00", "2026-01-01T10:20:00+00:00"),
        ("2026-01-01T12:20:00+02:00", "2026-01-01T10:20:00+00:00"),
    ],
    ids=["summer", "winter-defective-offset", "winter-correct-offset"],
)
def test_ims_wall_time_is_always_interpreted_as_fixed_utc_plus_two(raw, expected):
    normalized, preserved = normalize_ims_observation_timestamp(raw)

    assert normalized.isoformat() == expected
    assert preserved == raw


def test_timebase_produces_interval_ending_aggregation_window():
    evidence = select([station(1)], {"1": [observation(1)]}).wind_evidence

    assert evidence.wind_aggregation_end == evidence.wind_observed_at
    assert (
        evidence.wind_aggregation_end - evidence.wind_aggregation_start
    ).total_seconds() == 600.0


def test_result_is_strict_ea317_wind_evidence_with_selection_provenance():
    result = select([station(1)], {"1": [observation(1)]})
    evidence = result.wind_evidence

    assert isinstance(evidence, WindEvidence)
    assert evidence.provider == "IMS"
    assert evidence.source_type == "station_observation"
    assert evidence.provider_location_kind == "station"
    assert evidence.requested_coordinates == ORIGIN
    assert evidence.actual_provider_coordinates.latitude == 32.01
    assert evidence.retrieved_at == RETRIEVED_AT
    assert evidence.raw_provider_timestamp == "2026-07-01T12:20:00+03:00"
    assert evidence.provider_validity == "valid"
    assert evidence.reference == f"{IMS_API_ROOT}/stations/1/data"
    assert evidence.metadata["station_distance_m"] == result.station_distance_m
    serialized = evidence.model_dump(mode="json")
    assert not {
        "downwind_to_direction_deg",
        "bearing_from_origin_deg",
        "inside_transport_corridor",
        "kinematic_advection_time_seconds",
    } & serialized.keys()


def test_repeated_selection_is_deterministic_except_fixed_injected_clock():
    service = service_for([station(1)], {"1": [observation(1)]})
    arguments = dict(
        analysis_coordinates=ORIGIN,
        anomaly_observed_at=ANOMALY_TIME,
        maximum_observation_age_seconds=3600.0,
    )

    first = service.select_wind_evidence(**arguments)
    second = service.select_wind_evidence(**arguments)

    assert first == second


class FakeResponse:
    def __init__(
        self,
        payload: object,
        status_code: int = 200,
        *,
        content: bytes | None = None,
        content_type: str = "application/json",
        json_error: Exception | None = None,
        url: str | None = None,
        history: list[object] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.content = (
            json.dumps(payload).encode("utf-8") if content is None else content
        )
        self.headers = {"Content-Type": content_type}
        self.json_error = json_error
        self.url = url
        self.history = history or []

    def json(self) -> object:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response or FakeResponse([])
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def test_http_client_uses_header_auth_timeout_and_date_range_without_url_token():
    session = FakeSession()
    client = IMSWindObservationClient(api_token="highly-secret", session=session, timeout=7.0)

    client.get_station_data_range(17, date(2026, 6, 30), date(2026, 7, 1))

    url, request = session.calls[0]
    assert url == f"{IMS_API_ROOT}/stations/17/data"
    assert request["params"] == {"from": "2026/06/30", "to": "2026/07/01"}
    assert request["headers"]["Authorization"] == "ApiToken highly-secret"
    assert request["timeout"] == 7.0
    assert request["allow_redirects"] is True
    assert "highly-secret" not in url


def test_range_diagnostic_shows_exact_encoded_query_without_old_from_trailing_slash():
    diagnostics: list[IMSHTTPDiagnostic] = []
    client = IMSWindObservationClient(
        api_token="highly-secret",
        session=FakeSession(FakeResponse([])),
        diagnostic_callback=diagnostics.append,
    )

    client.get_station_data_range(17, date(2026, 6, 30), date(2026, 7, 1))

    request_url = diagnostics[0].request_url
    assert request_url.endswith(
        "?from=2026%2F06%2F30&to=2026%2F07%2F01"
    )
    assert "2026%2F06%2F30%2F" not in request_url


@pytest.mark.parametrize(
    "payload",
    [
        {"stationId": 1, "data": [observation(1)]},
        [observation(1)],
        {"observations": [observation(1)]},
    ],
    ids=["official-data-wrapper", "list", "observations-wrapper"],
)
def test_documented_latest_daily_and_range_observation_shapes_are_strictly_supported(payload):
    parsed_station = parse_ims_station_metadata(station(1))

    observations = parse_ims_wind_observations(payload, parsed_station)

    assert len(observations) == 1
    assert observations[0].wind_from_direction_deg == 270.0


def test_client_accepts_json_dict_and_list_and_reports_shape():
    for payload, expected_type in (({"data": []}, "dict"), ([], "list")):
        diagnostics: list[IMSHTTPDiagnostic] = []
        client = IMSWindObservationClient(
            api_token="highly-secret",
            session=FakeSession(FakeResponse(payload)),
            diagnostic_callback=diagnostics.append,
        )

        assert client.get_stations() == payload
        assert diagnostics[0].json_decoded is True
        assert diagnostics[0].json_type == expected_type


def test_empty_success_response_has_specific_error_and_diagnostic():
    diagnostics: list[IMSHTTPDiagnostic] = []
    client = IMSWindObservationClient(
        api_token="highly-secret",
        session=FakeSession(FakeResponse(None, content=b"")),
        diagnostic_callback=diagnostics.append,
    )

    with pytest.raises(IMSWindObservationError, match="empty_response"):
        client.get_stations()

    assert diagnostics[0].body_byte_length == 0
    assert diagnostics[0].error_category == "empty_response"


def test_non_json_success_response_has_specific_error_without_body_dump():
    diagnostics: list[IMSHTTPDiagnostic] = []
    client = IMSWindObservationClient(
        api_token="highly-secret",
        session=FakeSession(
            FakeResponse(
                None,
                content=b"<html>provider maintenance</html>",
                content_type="text/html",
                json_error=ValueError("not JSON"),
            )
        ),
        diagnostic_callback=diagnostics.append,
    )

    with pytest.raises(IMSWindObservationError, match="invalid_json"):
        client.get_stations()

    serialized = json.dumps(diagnostics[0].as_safe_dict())
    assert diagnostics[0].content_type == "text/html"
    assert diagnostics[0].body_byte_length == 33
    assert "provider maintenance" not in serialized


def test_valid_json_is_accepted_despite_wrong_content_type_and_reported():
    diagnostics: list[IMSHTTPDiagnostic] = []
    client = IMSWindObservationClient(
        api_token="highly-secret",
        session=FakeSession(FakeResponse([], content_type="text/plain")),
        diagnostic_callback=diagnostics.append,
    )

    assert client.get_stations() == []
    assert diagnostics[0].content_type == "text/plain"
    assert diagnostics[0].json_decoded is True


def test_json_scalar_has_unsupported_shape_error():
    client = IMSWindObservationClient(
        api_token="highly-secret", session=FakeSession(FakeResponse("ok"))
    )

    with pytest.raises(IMSWindObservationError, match="unsupported_response_shape"):
        client.get_stations()


def test_redirect_history_and_final_url_are_reported_without_credentials():
    redirect = FakeResponse(
        {},
        status_code=302,
        url=f"{IMS_API_ROOT}/old",
    )
    diagnostics: list[IMSHTTPDiagnostic] = []
    client = IMSWindObservationClient(
        api_token="highly-secret",
        session=FakeSession(
            FakeResponse(
                [],
                url=f"{IMS_API_ROOT}/stations",
                history=[redirect],
            )
        ),
        diagnostic_callback=diagnostics.append,
    )

    client.get_stations()

    assert diagnostics[0].redirect_statuses == (302,)
    assert diagnostics[0].redirect_urls == (f"{IMS_API_ROOT}/old",)
    assert diagnostics[0].final_url == f"{IMS_API_ROOT}/stations"


def test_debug_diagnostics_redact_token_from_all_provider_controlled_strings():
    diagnostics: list[IMSHTTPDiagnostic] = []
    client = IMSWindObservationClient(
        api_token="highly-secret",
        session=FakeSession(
            FakeResponse(
                {"highly-secret": []},
                content_type="application/highly-secret+json",
                url=f"{IMS_API_ROOT}/stations?token=highly-secret",
            )
        ),
        diagnostic_callback=diagnostics.append,
    )

    client.get_stations()

    assert "highly-secret" not in json.dumps(diagnostics[0].as_safe_dict())


@pytest.mark.parametrize(
    ("session", "category"),
    [
        (FakeSession(error=requests.Timeout("secret should not escape")), "timeout"),
        (FakeSession(error=requests.ConnectionError("secret should not escape")), "network_error"),
        (FakeSession(FakeResponse({}, status_code=401)), "authentication_failed"),
        (FakeSession(FakeResponse({}, status_code=403)), "authentication_failed"),
        (FakeSession(FakeResponse({}, status_code=404)), "not_found"),
        (FakeSession(FakeResponse({}, status_code=500)), "provider_http_error"),
    ],
)
def test_http_failures_are_controlled_and_never_echo_token(session, category):
    client = IMSWindObservationClient(api_token="highly-secret", session=session)

    with pytest.raises(IMSWindObservationError, match=category) as error:
        client.get_stations()

    assert error.value.category == category
    assert "highly-secret" not in str(error.value)
    assert "secret should not escape" not in str(error.value)


def test_token_is_absent_from_serialized_evidence_and_errors():
    evidence_json = json.dumps(
        select([station(1)], {"1": [observation(1)]}).model_dump(mode="json")
    )
    assert "IMS_API_TOKEN" not in evidence_json
    assert "ApiToken" not in evidence_json


def test_selection_uses_documented_daily_resource_not_ambiguous_range_query():
    client = FakeIMSClient([station(1)], {"1": [observation(1)]})
    service = IMSWindEvidenceService(client, clock=lambda: RETRIEVED_AT)  # type: ignore[arg-type]

    service.select_wind_evidence(
        analysis_coordinates=ORIGIN,
        anomaly_observed_at=ANOMALY_TIME,
        maximum_observation_age_seconds=3600.0,
    )

    assert client.daily_calls == [("1", date(2026, 7, 1))]
    assert client.range_calls == []


def test_naive_anomaly_time_and_nonfinite_policy_values_are_rejected():
    service = service_for([station(1)], {"1": [observation(1)]})
    with pytest.raises(ValueError, match="timezone-aware"):
        service.select_wind_evidence(
            analysis_coordinates=ORIGIN,
            anomaly_observed_at=datetime(2026, 7, 1, 10, 30),
            maximum_observation_age_seconds=3600.0,
        )
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite"):
            service.select_wind_evidence(
                analysis_coordinates=ORIGIN,
                anomaly_observed_at=ANOMALY_TIME,
                maximum_observation_age_seconds=value,
            )


def test_models_reject_unknown_fields_and_nonfinite_normalized_values():
    parsed = parse_ims_station_metadata(station(1))
    with pytest.raises(ValidationError):
        parsed.__class__(**parsed.model_dump(), unexpected=True)
    with pytest.raises(ValueError, match="finite"):
        normalize_ims_wind_observation(
            observation(1, wd=float("inf")), parsed
        )
