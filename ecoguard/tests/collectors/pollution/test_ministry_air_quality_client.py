"""Focused mocked tests for the Ministry air-quality collection adapter."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import pytest

from ecoguard.shared.ministry_air_quality_client import (
    ACCESS_TOKEN_URL,
    GUEST_TOKEN_URL,
    MinistryAirQualityClient,
    MinistryAirQualityError,
)


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self.payload


class FakeSession:
    """Small requests.Session substitute with deterministic queued responses."""

    def __init__(
        self,
        routes: dict[str, list[FakeResponse]] | None = None,
        *,
        guest_response: FakeResponse | None = None,
        exchange_response: FakeResponse | None = None,
        issue_cookie: bool = True,
        cookie_values: list[str] | None = None,
    ) -> None:
        self.routes = routes or {}
        self.guest_response = guest_response or FakeResponse("guest-api-token")
        self.exchange_response = exchange_response or FakeResponse(60)
        self.issue_cookie = issue_cookie
        self.cookie_values = cookie_values or ["access-cookie"]
        self.cookie_issue_count = 0
        self.cookies: dict[str, str] = {}
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: defaultdict[str, int] = defaultdict(int)
        self.get_requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, kwargs))
        if url == GUEST_TOKEN_URL:
            return self.guest_response
        if url == ACCESS_TOKEN_URL:
            if self.issue_cookie and self.exchange_response.status_code < 400:
                index = min(self.cookie_issue_count, len(self.cookie_values) - 1)
                self.cookies["X-Access-Token"] = self.cookie_values[index]
                self.cookie_issue_count += 1
            return self.exchange_response
        raise AssertionError(f"Unexpected POST endpoint: {url}")

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        endpoint = url.split("/envista/", maxsplit=1)[-1]
        self.get_calls[endpoint] += 1
        self.get_requests.append((url, kwargs))
        queue = self.routes.get(endpoint)
        if not queue:
            raise AssertionError(f"Unexpected GET endpoint: {endpoint}")
        return queue.pop(0) if len(queue) > 1 else queue[0]


def station(
    station_id: int = 17,
    *,
    latitude: float = 32.0853,
    longitude: float = 34.7818,
    monitors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "stationId": station_id,
        "name": f"Station {station_id}",
        "shortName": f"S{station_id}",
        "location": {"latitude": latitude, "longitude": longitude},
        "city": "Tel Aviv",
        "address": "Example address",
        "owner": "Ministry",
        "active": True,
        "monitors": monitors or [],
    }


def channel(
    name: str,
    value: float,
    *,
    channel_id: int = 101,
    unit: str = "mg/m³",
    valid: bool = True,
    status: int = 1,
    timestamp: str = "2026-09-07T10:15:00+02:00",
) -> dict[str, Any]:
    return {
        "id": channel_id,
        "name": name,
        "pollutantId": channel_id + 1000,
        "units": unit,
        "value": value,
        "datetime": timestamp,
        "valid": valid,
        "active": True,
        "status": status,
    }


def routes_for(
    channels_by_station: dict[int, list[dict[str, Any]]],
    *,
    stations: list[dict[str, Any]] | None = None,
    statuses: list[dict[str, Any]] | None = None,
) -> dict[str, list[FakeResponse]]:
    station_list = stations or [
        station(station_id) for station_id in channels_by_station
    ]
    latest = [
        {"stationId": station_id, "regionData": {"channels": channels}}
        for station_id, channels in channels_by_station.items()
    ]
    return {
        "regions": [FakeResponse([{"regionId": 2, "stations": station_list}])],
        "data/status": [
            FakeResponse(statuses or [{"Id": 1, "Name": "Normal"}])
        ],
        "regions/data/latest": [FakeResponse(latest)],
    }


def index_routes(index_payload: Any) -> dict[str, list[FakeResponse]]:
    return {
        "stations/17/indexFastSrv": [FakeResponse(index_payload)],
        "regions": [
            FakeResponse(
                [
                    {
                        "regionId": 2,
                        "stations": [
                            station(
                                monitors=[
                                    {
                                        "channelId": 101,
                                        "name": "PM2.5",
                                        "pollutantId": 1101,
                                        "units": "ug/m3",
                                        "active": True,
                                    }
                                ]
                            )
                        ],
                    }
                ]
            )
        ],
    }


def native_index_payload(**detail_changes: Any) -> dict[str, Any]:
    detail = {
        "pollutant": "PM2.5",
        "index": 72,
        "value": 18.4,
        "PollutantTimeBase": 1440,
        "MonitorId": 101,
    }
    detail.update(detail_changes)
    return {
        "data": [
            {
                "stationId": 17,
                "datetime": "2026-09-07T10:30:00+02:00",
                "index": 67,
                "description": "טובה",
                "color": "#00A651",
                "pollutant": "PM2.5",
                "indexes": [detail],
            }
        ]
    }


def test_native_ministry_index_preserves_category_monitor_and_timebase():
    clock = lambda: datetime(2026, 9, 7, 8, 31, tzinfo=timezone.utc)
    client = MinistryAirQualityClient(
        session=FakeSession(index_routes(native_index_payload())), clock=clock
    )

    result = client.get_station_index_evidence(
        station_id="17",
        channel_id="101",
        pollutant="PM2.5",
        observed_at=datetime(2026, 9, 7, 8, 15, tzinfo=timezone.utc),
    )

    assert result.status == "available"
    evidence = result.evidence
    assert evidence.station_index == 67
    assert evidence.station_category == "טובה"
    assert evidence.pollutant_sub_index == 72
    assert evidence.monitor_id == evidence.resolved_channel_id == "101"
    assert evidence.averaging_period_minutes == 1440
    assert evidence.averaged_concentration == 18.4
    assert evidence.unit_source == "station_metadata"
    assert evidence.provider_unit == "ug/m3"
    assert evidence.preliminary is True
    assert evidence.classification_system == "ministry_air_quality_index"
    assert not {"us_aqi", "aqi_category", "ecoguard_severity_level"} & set(
        type(evidence).model_fields
    )


def test_native_index_selects_only_the_requested_pollutant_sub_index():
    payload = native_index_payload()
    payload["data"][0]["indexes"].insert(
        0,
        {
            "pollutant": "NO2",
            "index": 999,
            "value": 999,
            "PollutantTimeBase": 60,
            "MonitorId": 202,
        },
    )
    result = MinistryAirQualityClient(
        session=FakeSession(index_routes(payload))
    ).get_station_index_evidence(
        station_id="17",
        channel_id="101",
        pollutant="PM2.5",
        observed_at=datetime(2026, 9, 7, 8, 15, tzinfo=timezone.utc),
    )

    assert result.status == "available"
    assert result.evidence.pollutant == "PM2.5"
    assert result.evidence.pollutant_sub_index == 72
    assert result.evidence.monitor_id == "101"


@pytest.mark.parametrize(
    ("changes", "channel_id", "pollutant", "reason"),
    [
        ({"index": -9999}, "101", "PM2.5", "no_valid_index"),
        ({"index": "No Index"}, "101", "PM2.5", "no_valid_index"),
        ({"MonitorId": 999}, "101", "PM2.5", "channel_mismatch"),
        ({"pollutant": "NO2"}, "101", "PM2.5", "pollutant_mismatch"),
    ],
)
def test_native_index_rejects_invalid_or_mismatched_details(
    changes, channel_id, pollutant, reason
):
    client = MinistryAirQualityClient(
        session=FakeSession(index_routes(native_index_payload(**changes)))
    )
    result = client.get_station_index_evidence(
        station_id="17",
        channel_id=channel_id,
        pollutant=pollutant,
        observed_at=datetime(2026, 9, 7, 8, 15, tzinfo=timezone.utc),
    )
    assert result.status == "unavailable"
    assert result.reason == reason


def test_native_index_rejects_station_and_temporal_mismatch():
    wrong_station = native_index_payload()
    wrong_station["data"][0]["stationId"] = 18
    result = MinistryAirQualityClient(
        session=FakeSession(index_routes(wrong_station))
    ).get_station_index_evidence(
        station_id="17",
        channel_id="101",
        pollutant="PM2.5",
        observed_at=datetime(2026, 9, 7, 8, 15, tzinfo=timezone.utc),
    )
    assert result.reason == "station_mismatch"

    result = MinistryAirQualityClient(
        session=FakeSession(index_routes(native_index_payload()))
    ).get_station_index_evidence(
        station_id="17",
        channel_id="101",
        pollutant="PM2.5",
        observed_at=datetime(2026, 9, 6, 7, 0, tzinfo=timezone.utc),
    )
    assert result.reason == "timestamp_incompatible"


def test_guest_authentication_uses_api_token_header_and_access_cookie():
    session = FakeSession({"pollutants": [FakeResponse([])]})
    client = MinistryAirQualityClient(session=session)

    assert client.get_pollutants() == []
    assert [call[0] for call in session.post_calls] == [
        GUEST_TOKEN_URL,
        ACCESS_TOKEN_URL,
    ]
    assert session.post_calls[0][1]["json"] == {"userName": "Guest"}
    assert session.post_calls[1][1]["headers"]["Authorization"] == (
        "ApiToken guest-api-token"
    )
    assert session.cookies["X-Access-Token"] == "access-cookie"
    guest_verification = session.post_calls[0][1]["headers"][
        "x-requestverificationtoken"
    ]
    exchange_verification = session.post_calls[1][1]["headers"][
        "x-requestverificationtoken"
    ]
    envista_headers = session.get_requests[0][1]["headers"]
    assert guest_verification == exchange_verification
    assert envista_headers["x-requestverificationtoken"] == guest_verification
    assert envista_headers["Authorization"] == "JwtToken access-cookie"
    assert envista_headers["Authorization"] != "JwtToken 60"


@pytest.mark.parametrize(
    ("session", "category"),
    [
        (
            FakeSession(guest_response=FakeResponse({}, status_code=403)),
            "authentication_failed",
        ),
        (FakeSession(issue_cookie=False), "access_cookie_missing"),
    ],
)
def test_authentication_failures_are_explicit(session: FakeSession, category: str):
    client = MinistryAirQualityClient(session=session)

    with pytest.raises(MinistryAirQualityError, match=category) as error:
        client.get_pollutants()

    assert error.value.category == category


def test_unauthorized_request_reauthenticates_once_and_retries():
    session = FakeSession(
        {
            "pollutants": [
                FakeResponse({}, status_code=401),
                FakeResponse([{"Id": 1, "Name": "PM2.5"}]),
            ]
        },
        cookie_values=["access-cookie-1", "access-cookie-2"],
    )
    client = MinistryAirQualityClient(session=session)

    assert client.get_pollutants()[0]["Name"] == "PM2.5"
    assert len(session.post_calls) == 4
    assert session.get_calls["pollutants"] == 2
    first_verification = session.post_calls[0][1]["headers"][
        "x-requestverificationtoken"
    ]
    renewed_verification = session.post_calls[2][1]["headers"][
        "x-requestverificationtoken"
    ]
    assert session.post_calls[1][1]["headers"][
        "x-requestverificationtoken"
    ] == first_verification
    assert session.post_calls[3][1]["headers"][
        "x-requestverificationtoken"
    ] == renewed_verification
    assert renewed_verification != first_verification
    assert session.get_requests[0][1]["headers"]["Authorization"] == (
        "JwtToken access-cookie-1"
    )
    assert session.get_requests[1][1]["headers"]["Authorization"] == (
        "JwtToken access-cookie-2"
    )
    assert session.get_requests[1][1]["headers"][
        "x-requestverificationtoken"
    ] == renewed_verification


def test_unauthorized_retry_occurs_only_once():
    session = FakeSession(
        {
            "pollutants": [
                FakeResponse({}, status_code=401),
                FakeResponse({}, status_code=403),
            ]
        },
        cookie_values=["access-cookie-1", "access-cookie-2"],
    )
    client = MinistryAirQualityClient(session=session)

    with pytest.raises(MinistryAirQualityError, match="unauthorized"):
        client.get_pollutants()

    assert session.get_calls["pollutants"] == 2
    assert len(session.post_calls) == 4


def test_station_metadata_normalizes_optional_fields_and_excludes_bad_coordinates():
    minimal = {
        "stationId": 18,
        "name": "Minimal station",
        "location": {"latitude": 31.5, "longitude": 34.75},
    }
    session = FakeSession(
        {
            "regions": [
                FakeResponse(
                    [
                        {
                            "regionId": 2,
                            "stations": [
                                station(
                                    monitors=[
                                        {
                                            "channelId": 0,
                                            "name": "NOx",
                                            "pollutantId": 9,
                                            "units": "ppb",
                                            "active": True,
                                        }
                                    ]
                                ),
                                minimal,
                                station(19, latitude=95.0),
                            ],
                        }
                    ]
                )
            ]
        }
    )
    result = MinistryAirQualityClient(session=session).get_station_metadata()

    assert result.status == "partial"
    assert result.excluded_count == 1
    assert len(result.stations) == 2
    assert result.stations[0].monitors[0].provider_channel_id == "0"
    assert result.stations[0].monitors[0].pollutant == "NOx"
    assert result.stations[1].city is None
    assert result.stations[1].provider_region_id == "2"


def test_latest_collection_normalizes_pollutants_units_time_and_station_subsets():
    routes = routes_for(
        {
            17: [
                channel("PM2.5", 0.018, unit="mg/m³"),
                channel("NO", 14.0, channel_id=102, unit="ppb"),
                channel("NOX", 20.0, channel_id=103, unit="ppb"),
            ],
            18: [
                channel("Benzene", 1000.0, channel_id=201, unit="ng/m3"),
                channel("H2S", 2.0, channel_id=202, unit="ppb"),
            ],
        }
    )
    result = MinistryAirQualityClient(session=FakeSession(routes)).collect_latest()

    assert result.status == "success"
    assert {item.pollutant for item in result.observations} == {
        "PM2.5",
        "NO",
        "NOx",
        "Benzene",
        "H2S",
    }
    benzene = next(item for item in result.observations if item.pollutant == "Benzene")
    assert benzene.value == 1000.0
    assert benzene.unit == "ng/m³"
    assert benzene.provider_unit == "ng/m3"
    assert benzene.observed_at == datetime(2026, 9, 7, 8, 15, tzinfo=timezone.utc)
    assert benzene.provider_timestamp == "2026-09-07T10:15:00+02:00"
    assert benzene.quality_control == "preliminary_unvalidated"


@pytest.mark.parametrize(
    ("reading", "statuses", "reason"),
    [
        (channel("PM10", -9999.0), None, "invalid_sentinel"),
        (channel("PM10", 10.0, valid=False), None, "provider_marked_invalid"),
        (
            channel("PM10", 10.0, status=2, valid=False),
            [{"Id": 2, "Name": "Calib"}],
            "provider_marked_invalid",
        ),
        (
            channel("PM10", 10.0, status=3, valid=False),
            [{"Id": 3, "Name": "Down"}],
            "provider_marked_invalid",
        ),
        (
            channel("PM10", 10.0, status=4, valid=False),
            [{"Id": 4, "Name": "NoData"}],
            "provider_marked_invalid",
        ),
        (
            channel("PM10", 10.0, status=5, valid=False),
            [{"Id": 5, "Name": "InVld"}],
            "provider_marked_invalid",
        ),
    ],
)
def test_invalid_quality_readings_are_excluded_with_audit_reason(
    reading: dict[str, Any], statuses: list[dict[str, Any]] | None, reason: str
):
    result = MinistryAirQualityClient(
        session=FakeSession(routes_for({17: [reading]}, statuses=statuses))
    ).collect_latest()

    assert result.status == "partial"
    assert result.observations == []
    assert result.excluded[0].reason == reason
    assert result.excluded[0].provider_channel_id == "101"


def test_bad_channels_do_not_discard_valid_channels_and_weather_is_filtered():
    valid = channel("O3", 31.0, channel_id=101, unit="ppb")
    unsupported_unit = channel("CO", 1.2, channel_id=102, unit="percent")
    weather = channel("Temperature", 27.0, channel_id=103, unit="ppm")
    malformed_time = channel("SO2", 2.0, channel_id=104, timestamp="not-a-time")
    result = MinistryAirQualityClient(
        session=FakeSession(
            routes_for({17: [valid, unsupported_unit, weather, malformed_time]})
        )
    ).collect_latest()

    assert [item.pollutant for item in result.observations] == ["O3"]
    assert {item.reason for item in result.excluded} == {
        "unsupported_unit",
        "unsupported_pollutant",
        "malformed_timestamp",
    }
    assert result.status == "partial"


@pytest.mark.parametrize(
    ("provider_unit", "canonical_unit"),
    [
        ("ug/m3", "µg/m³"),
        ("µg/m3", "µg/m³"),
        ("mg/m3", "mg/m³"),
        ("ng/m3", "ng/m³"),
        ("ppb", "ppb"),
        ("ppm", "ppm"),
    ],
)
def test_known_provider_units_are_normalized_without_value_conversion(
    provider_unit: str, canonical_unit: str
):
    result = MinistryAirQualityClient(
        session=FakeSession(
            routes_for({17: [channel("PM1", 1000.0, unit=provider_unit)]})
        )
    ).collect_latest()

    observation = result.observations[0]
    assert observation.value == 1000.0
    assert observation.unit == canonical_unit
    assert observation.provider_unit == provider_unit


def test_provider_status_metadata_failure_keeps_valid_data_as_partial():
    routes = routes_for({17: [channel("SO2", 2.5, unit="ppb")]})
    routes["data/status"] = [FakeResponse({}, status_code=503)]
    result = MinistryAirQualityClient(session=FakeSession(routes)).collect_latest()

    assert [item.pollutant for item in result.observations] == ["SO2"]
    assert result.status == "partial"
    assert result.errors == ["status_metadata_provider_http_error"]


def test_provider_failure_returns_failed_collection_without_fallback_data():
    session = FakeSession(
        {
            "regions": [FakeResponse([{"regionId": 2, "stations": [station()]}])],
            "data/status": [FakeResponse([])],
            "regions/data/latest": [FakeResponse({}, status_code=503)],
        }
    )
    result = MinistryAirQualityClient(session=session).collect_latest()

    assert result.status == "failed"
    assert result.observations == []
    assert result.errors == ["provider_http_error"]


def test_static_reference_metadata_is_reused_within_ttl():
    now = [100.0]
    session = FakeSession({"pollutants": [FakeResponse([{"Id": 1}])]})
    client = MinistryAirQualityClient(
        session=session,
        reference_ttl_seconds=60,
        monotonic=lambda: now[0],
    )

    client.get_pollutants()
    client.get_pollutants()
    assert session.get_calls["pollutants"] == 1

    now[0] += 61
    client.get_pollutants()
    assert session.get_calls["pollutants"] == 2
