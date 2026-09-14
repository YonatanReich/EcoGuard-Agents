"""Read-only client for Israel's National Air Monitoring Network.

The client implements the public website's guest cookie flow and normalizes
provider readings. It makes no anomaly, emergency, or response decisions and
has no persistence dependency.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from pydantic import ValidationError

from ecoguard.shared.air_quality_schemas import PollutantObservation, LIVE_QUALITY_POLICY
from ecoguard.shared.air_quality_schemas import (
    AirQualityCollectionResult,
    AirQualityMonitor,
    AirQualityObservation,
    AirQualityStation,
    ExcludedAirQualityReading,
    MinistryAirQualityIndexEvidence,
    MinistryAirQualityIndexLookupResult,
    StationCollectionResult,
)

PUBLIC_SITE = "https://air.sviva.gov.il"
API_ROOT = "https://air-papi.sviva.gov.il/v1"
ENVISTA_ROOT = f"{API_ROOT}/envista"
GUEST_TOKEN_URL = f"{PUBLIC_SITE}/Account/GetApiToken"
ACCESS_TOKEN_URL = f"{API_ROOT}/GenerateToken"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_REFERENCE_TTL_SECONDS = 6 * 60 * 60
INVALID_READING_SENTINEL = -9999.0
MINISTRY_INDEX_CLOCK = timezone(timedelta(hours=2), "Ministry fixed UTC+02:00")

RECOGNIZED_POLLUTANTS = frozenset(
    {
        "PM2.5",
        "PM10",
        "PM1",
        "PM4",
        "NO2",
        "NO",
        "NOX",
        "O3",
        "CO",
        "CO2",
        "SO2",
        "BENZENE",
        "ETHYLBENZENE",
        "H2S",
        "TSP",
        "TSPM",
        "TPM",
        "PM",
    }
)

POLLUTANT_CANONICAL_NAMES = {
    "NOX": "NOx",
    "BENZENE": "Benzene",
    "ETHYLBENZENE": "Ethylbenzene",
    "TSPM": "TSP",
    "TPM": "TSP",
}

PROVIDER_UNIT_ALIASES = {
    "ug/m3": "µg/m³",
    "µg/m3": "µg/m³",
    "μg/m3": "µg/m³",
    "mg/m3": "mg/m³",
    "ng/m3": "ng/m³",
}

UNUSABLE_STATUS_NAMES = frozenset(
    {"NODATA", "DOWN", "INVLD", "INVALID", "CALIB", "CALIBRATION"}
)


class MinistryAirQualityError(RuntimeError):
    """Credential-safe provider failure."""

    def __init__(self, category: str, *, transient: bool):
        super().__init__(category)
        self.category = category
        self.transient = transient


def _text(value: object | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _parse_provider_timestamp(value: object) -> tuple[datetime, str]:
    raw = _text(value)
    if raw is None:
        raise ValueError("timestamp missing")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("timestamp malformed") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp lacks UTC offset")
    return parsed.astimezone(timezone.utc), raw


def _provider_id(value: object | None) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    return _text(value)


def _first_present(values: Mapping[str, Any], *keys: str) -> object | None:
    """Return the first present, non-null provider value without losing zero IDs."""
    for key in keys:
        value = values.get(key)
        if value is not None:
            return value
    return None


def _canonical_unit(value: object | None) -> str | None:
    provider_unit = _text(value)
    if provider_unit is None:
        return None
    return PROVIDER_UNIT_ALIASES.get(provider_unit, provider_unit)


def _mapping_value(values: Mapping[str, Any], *keys: str) -> object | None:
    """Read known provider key variants without broad heuristic parsing."""
    direct = _first_present(values, *keys)
    if direct is not None:
        return direct
    lowered = {str(key).lower(): value for key, value in values.items()}
    return _first_present(lowered, *(key.lower() for key in keys))


def _finite_index_number(value: object | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "no index":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number == INVALID_READING_SENTINEL:
        return None
    return number


def _parse_index_timestamp(value: object | None) -> tuple[datetime, str] | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    # This is the provider's documented/index-response fixed clock contract,
    # not Asia/Jerusalem civil time or an inferred DST conversion.
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=MINISTRY_INDEX_CLOCK)
    if parsed.utcoffset() != timedelta(hours=2):
        return None
    return parsed.astimezone(timezone.utc), raw


class MinistryAirQualityClient:
    """Cookie-preserving, injectable Ministry provider client."""

    def __init__(
        self,
        *,
        session: Any | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        reference_ttl_seconds: float = DEFAULT_REFERENCE_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if timeout <= 0 or reference_ttl_seconds < 0:
            raise ValueError("timeout must be positive and cache TTL non-negative")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.reference_ttl_seconds = reference_ttl_seconds
        self.monotonic = monotonic
        self.clock = clock
        self._authenticated = False
        self._request_verification_token: str | None = None
        self._access_credential: str | None = None
        self._auth_lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}

    def _headers(self, *, authenticated: bool = False) -> dict[str, str]:
        if self._request_verification_token is None:
            raise MinistryAirQualityError("authentication_required", transient=False)
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": PUBLIC_SITE,
            "Referer": f"{PUBLIC_SITE}/",
            "domainname": "sviva",
            "envi-data-source": "MANA",
            "x-requestverificationtoken": self._request_verification_token,
            "User-Agent": "EcoGuard-Agents air-quality-collector/1.0",
        }
        if authenticated:
            if self._access_credential is None:
                raise MinistryAirQualityError(
                    "authentication_required", transient=False
                )
            headers["Authorization"] = f"JwtToken {self._access_credential}"
        return headers

    def _start_authentication_lifecycle(self) -> None:
        self._authenticated = False
        self._request_verification_token = str(uuid.uuid4())
        self._access_credential = None
        cookie_jar = self.session.cookies
        for cookie in list(cookie_jar):
            if getattr(cookie, "name", None) == "X-Access-Token":
                cookie_jar.clear(cookie.domain, cookie.path, cookie.name)
        if isinstance(cookie_jar, dict):
            cookie_jar.pop("X-Access-Token", None)

    @staticmethod
    def _response_json(response: Any) -> Any:
        try:
            return response.json()
        except (TypeError, ValueError):
            raise MinistryAirQualityError(
                "malformed_response", transient=False
            ) from None

    @staticmethod
    def _raise_for_status(response: Any, *, authentication: bool = False) -> None:
        status = int(getattr(response, "status_code", 0))
        if status < 400:
            return
        if status in {401, 403}:
            category = "authentication_failed" if authentication else "unauthorized"
            raise MinistryAirQualityError(category, transient=True)
        raise MinistryAirQualityError(
            "provider_http_error", transient=status == 429 or status >= 500
        )

    def _authenticate(self, *, force: bool = False) -> None:
        with self._auth_lock:
            if self._authenticated and not force:
                return
            self._start_authentication_lifecycle()
            headers = self._headers()
            try:
                guest_response = self.session.post(
                    GUEST_TOKEN_URL,
                    json={"userName": "Guest"},
                    headers=headers,
                    timeout=self.timeout,
                )
                self._raise_for_status(guest_response, authentication=True)
                payload = self._response_json(guest_response)
                if isinstance(payload, str):
                    guest_token = payload.strip()
                elif isinstance(payload, Mapping):
                    guest_token = _text(payload.get("token") or payload.get("apiToken"))
                else:
                    guest_token = None
                if not guest_token:
                    raise MinistryAirQualityError(
                        "authentication_malformed", transient=False
                    )
                exchange_headers = self._headers()
                exchange_headers["Authorization"] = f"ApiToken {guest_token}"
                access_response = self.session.post(
                    ACCESS_TOKEN_URL,
                    json={},
                    headers=exchange_headers,
                    timeout=self.timeout,
                )
                self._raise_for_status(access_response, authentication=True)
                # The response body is lifetime metadata (observed as "60").
                # The actual credential must exist in the session cookie jar.
                access_cookie = self.session.cookies.get("X-Access-Token")
                if not access_cookie:
                    raise MinistryAirQualityError(
                        "access_cookie_missing", transient=False
                    )
                self._access_credential = str(access_cookie)
                self._authenticated = True
            except requests.Timeout:
                raise MinistryAirQualityError("timeout", transient=True) from None
            except requests.RequestException:
                raise MinistryAirQualityError("network_error", transient=True) from None

    def _get_json(
        self, endpoint: str, *, params: Mapping[str, Any] | None = None
    ) -> Any:
        self._authenticate()
        for attempt in range(2):
            try:
                response = self.session.get(
                    f"{ENVISTA_ROOT}/{endpoint}",
                    params=dict(params or {}),
                    headers=self._headers(authenticated=True),
                    timeout=self.timeout,
                )
                unauthorized = int(getattr(response, "status_code", 0)) in {401, 403}
                if unauthorized and attempt == 0:
                    self._authenticate(force=True)
                    continue
                self._raise_for_status(response)
                return self._response_json(response)
            except requests.Timeout:
                raise MinistryAirQualityError("timeout", transient=True) from None
            except requests.RequestException:
                raise MinistryAirQualityError("network_error", transient=True) from None
        raise MinistryAirQualityError("authentication_failed", transient=True)

    def _cached_get(self, key: str, endpoint: str) -> Any:
        cached = self._cache.get(key)
        now = self.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]
        payload = self._get_json(endpoint)
        self._cache[key] = (now + self.reference_ttl_seconds, payload)
        return payload

    def get_pollutants(self) -> list[dict[str, Any]]:
        return self._reference_list("pollutants", "pollutants")

    def get_units(self) -> list[dict[str, Any]]:
        return self._reference_list("units", "data/units")

    def get_statuses(self) -> list[dict[str, Any]]:
        return self._reference_list("statuses", "data/status")

    def get_station_index_evidence(
        self,
        *,
        station_id: str,
        channel_id: str,
        pollutant: str,
        observed_at: datetime,
    ) -> MinistryAirQualityIndexLookupResult:
        """Match one event to native Ministry index evidence, or fail closed.

        The native index has its own pollutant-specific averaging period.  A
        triggering five-minute observation is associated only when its instant
        falls within that backward-looking provider window; the two values are
        never represented as the same measurement.
        """
        station_id = _provider_id(station_id) or ""
        channel_id = _provider_id(channel_id) or ""
        canonical_pollutant = self._canonical_pollutant(pollutant)
        if not station_id or not channel_id or canonical_pollutant is None:
            return MinistryAirQualityIndexLookupResult(
                status="unavailable", reason="invalid_event_identity"
            )
        if observed_at.utcoffset() is None:
            return MinistryAirQualityIndexLookupResult(
                status="unavailable", reason="invalid_event_timestamp"
            )
        event_time = observed_at.astimezone(timezone.utc)
        provider_day = event_time.astimezone(MINISTRY_INDEX_CLOCK).date().isoformat()
        try:
            payload = self._get_json(
                f"stations/{station_id}/indexFastSrv",
                params={
                    "from": f"{provider_day}T00:00:00",
                    "to": f"{provider_day}T23:59:59",
                },
            )
        except MinistryAirQualityError as error:
            return MinistryAirQualityIndexLookupResult(
                status="unavailable", reason=f"ministry_index_{error.category}"
            )
        result = self._match_station_index_payload(
            payload,
            station_id=station_id,
            channel_id=channel_id,
            pollutant=canonical_pollutant,
            event_time=event_time,
        )
        return result

    def _match_station_index_payload(
        self,
        payload: object,
        *,
        station_id: str,
        channel_id: str,
        pollutant: str,
        event_time: datetime,
    ) -> MinistryAirQualityIndexLookupResult:
        rows: list[Mapping[str, Any]] = []
        if isinstance(payload, Mapping):
            data = _mapping_value(payload, "data")
            if isinstance(data, list):
                rows.extend(item for item in data if isinstance(item, Mapping))
            else:
                rows.append(payload)
        elif isinstance(payload, list):
            rows.extend(item for item in payload if isinstance(item, Mapping))
        else:
            return MinistryAirQualityIndexLookupResult(
                status="unavailable", reason="malformed_index_response"
            )

        matches: list[MinistryAirQualityIndexEvidence] = []
        rejected: set[str] = set()
        station_metadata: AirQualityStation | None = None
        for row in rows:
            row_station = _provider_id(
                _mapping_value(row, "stationId", "StationId")
            )
            if row_station is not None and row_station != station_id:
                rejected.add("station_mismatch")
                continue
            details = _mapping_value(row, "indexes", "Indexes")
            if not isinstance(details, list):
                details = [row]
            for detail in details:
                if not isinstance(detail, Mapping):
                    continue
                raw_pollutant = _mapping_value(detail, "pollutant", "Pollutant")
                detail_pollutant = self._canonical_pollutant(raw_pollutant)
                if detail_pollutant != pollutant:
                    rejected.add("pollutant_mismatch")
                    continue
                monitor_id = _provider_id(
                    _mapping_value(detail, "MonitorId", "monitorId")
                )
                if monitor_id is None:
                    rejected.add("monitor_id_unresolved")
                    continue
                if monitor_id != channel_id:
                    rejected.add("channel_mismatch")
                    continue
                station_index = _finite_index_number(
                    _mapping_value(row, "index", "Index")
                )
                sub_index = _finite_index_number(
                    _mapping_value(detail, "index", "Index")
                )
                concentration = _finite_index_number(
                    _mapping_value(detail, "value", "Value")
                )
                category = _text(
                    _mapping_value(row, "description", "Description")
                )
                if (
                    station_index is None
                    or sub_index is None
                    or concentration is None
                    or category is None
                    or category.lower() == "no index"
                ):
                    rejected.add("no_valid_index")
                    continue
                timebase_raw = _mapping_value(
                    detail, "PollutantTimeBase", "pollutantTimeBase"
                )
                if isinstance(timebase_raw, bool):
                    timebase = None
                else:
                    try:
                        timebase = int(timebase_raw)
                    except (TypeError, ValueError):
                        timebase = None
                if timebase is None or timebase <= 0:
                    rejected.add("malformed_averaging_period")
                    continue
                parsed_time = _parse_index_timestamp(
                    _mapping_value(detail, "datetime", "DateTime")
                    or _mapping_value(row, "datetime", "DateTime")
                    or (
                        _mapping_value(payload, "datetime", "DateTime")
                        if isinstance(payload, Mapping)
                        else None
                    )
                )
                if parsed_time is None:
                    rejected.add("malformed_index_timestamp")
                    continue
                provider_time, raw_timestamp = parsed_time
                window_start = provider_time - timedelta(minutes=timebase)
                if not window_start < event_time <= provider_time:
                    rejected.add("timestamp_incompatible")
                    continue
                if station_metadata is None:
                    try:
                        station_metadata = next(
                            (
                                item
                                for item in self.get_station_metadata().stations
                                if item.provider_station_id == station_id
                            ),
                            None,
                        )
                    except MinistryAirQualityError:
                        station_metadata = None
                monitor = next(
                    (
                        item
                        for item in (
                            station_metadata.monitors
                            if station_metadata is not None
                            else []
                        )
                        if item.provider_channel_id == monitor_id
                        and item.pollutant == pollutant
                    ),
                    None,
                )
                provider_unit = monitor.provider_unit if monitor is not None else None
                canonical_unit = monitor.unit if monitor is not None else None
                driving = self._canonical_pollutant(
                    _mapping_value(row, "pollutant", "Pollutant")
                )
                if driving is None:
                    rejected.add("driving_pollutant_unavailable")
                    continue
                retrieved_at = self.clock().astimezone(timezone.utc)
                matches.append(
                    MinistryAirQualityIndexEvidence(
                        station_id=station_id,
                        station_index=station_index,
                        station_category=category,
                        category_color=_text(
                            _mapping_value(row, "color", "Color")
                        ),
                        driving_pollutant=driving,
                        pollutant=pollutant,
                        pollutant_sub_index=sub_index,
                        monitor_id=monitor_id,
                        resolved_channel_id=channel_id,
                        averaged_concentration=concentration,
                        canonical_unit=canonical_unit,
                        provider_unit=provider_unit,
                        unit_source=(
                            "station_metadata" if monitor is not None else "unknown"
                        ),
                        averaging_period_minutes=timebase,
                        provider_timestamp=provider_time,
                        raw_provider_timestamp=raw_timestamp,
                        evidence_id=(
                            "ministry-aqi:"
                            f"{station_id}:{monitor_id}:{pollutant}:"
                            f"{provider_time.isoformat()}"
                        ),
                        retrieved_at=retrieved_at,
                        limitations=[
                            "Source-native Ministry category; no EcoGuard LOW/MEDIUM/HIGH mapping.",
                            "Preliminary provider data may change after validation.",
                            "The index concentration uses its provider averaging window and is not the triggering five-minute measurement.",
                        ],
                    )
                )
        if matches:
            closest = min(
                matches,
                key=lambda item: abs((item.provider_timestamp - event_time).total_seconds()),
            )
            return MinistryAirQualityIndexLookupResult(
                status="available", evidence=closest
            )
        reason_priority = (
            "station_mismatch",
            "pollutant_mismatch",
            "monitor_id_unresolved",
            "channel_mismatch",
            "no_valid_index",
            "malformed_averaging_period",
            "malformed_index_timestamp",
            "timestamp_incompatible",
            "driving_pollutant_unavailable",
        )
        reason = next((item for item in reason_priority if item in rejected), None)
        return MinistryAirQualityIndexLookupResult(
            status="unavailable", reason=reason or "index_unavailable"
        )

    def _reference_list(self, key: str, endpoint: str) -> list[dict[str, Any]]:
        payload = self._cached_get(key, endpoint)
        if not isinstance(payload, list):
            raise MinistryAirQualityError("malformed_response", transient=False)
        return [dict(item) for item in payload if isinstance(item, Mapping)]

    def get_station_metadata(self) -> StationCollectionResult:
        payload = self._cached_get("regions", "regions")
        if not isinstance(payload, list):
            raise MinistryAirQualityError("malformed_response", transient=False)
        stations: list[AirQualityStation] = []
        excluded_count = 0
        for region in payload:
            if not isinstance(region, Mapping):
                excluded_count += 1
                continue
            raw_stations = region.get("stations") or []
            if not isinstance(raw_stations, list):
                excluded_count += 1
                continue
            for station in raw_stations:
                try:
                    normalized = self._normalize_station(
                        station, region.get("regionId")
                    )
                except (TypeError, ValueError, ValidationError):
                    excluded_count += 1
                    continue
                stations.append(normalized)
        status = "partial" if excluded_count else "success"
        return StationCollectionResult(
            status=status,
            stations=stations,
            excluded_count=excluded_count,
            errors=["invalid_station_metadata"] if excluded_count else [],
        )

    @staticmethod
    def _canonical_pollutant(raw_name: object) -> str | None:
        name = _text(raw_name)
        if name is None or name.upper() not in RECOGNIZED_POLLUTANTS:
            return None
        return POLLUTANT_CANONICAL_NAMES.get(name.upper(), name)

    @classmethod
    def _normalize_monitor(cls, raw: Mapping[str, Any]) -> AirQualityMonitor | None:
        pollutant = cls._canonical_pollutant(raw.get("name"))
        channel_id = _provider_id(_first_present(raw, "channelId", "id"))
        provider_unit = _text(raw.get("units"))
        if pollutant is None or channel_id is None or provider_unit is None:
            return None
        # Reuse the extracted measurement-only pollutant/unit validation.
        validated = PollutantObservation(
            pollutant=pollutant,
            provider_pollutant_id=_provider_id(raw.get("pollutantId")),
            value=0.0,
            unit=_canonical_unit(provider_unit),
            provider_unit=provider_unit,
        )
        return AirQualityMonitor(
            provider_channel_id=channel_id,
            pollutant=validated.pollutant,
            provider_pollutant_id=validated.provider_pollutant_id,
            unit=validated.unit,
            provider_unit=provider_unit,
            active=raw.get("active") if isinstance(raw.get("active"), bool) else None,
            provider_state=_text(raw.get("state")),
            percent_valid_required=raw.get("PctValid"),
        )

    @classmethod
    def _normalize_station(
        cls, raw: object, fallback_region_id: object = None
    ) -> AirQualityStation:
        if not isinstance(raw, Mapping):
            raise TypeError("station must be an object")
        location = raw.get("location")
        if not isinstance(location, Mapping):
            raise ValueError("station location missing")
        station_id = _provider_id(raw.get("stationId"))
        name = _text(raw.get("name"))
        if station_id is None or name is None:
            raise ValueError("station identity missing")
        monitors = []
        for monitor in raw.get("monitors") or []:
            if not isinstance(monitor, Mapping):
                continue
            try:
                normalized = cls._normalize_monitor(monitor)
            except (TypeError, ValueError, ValidationError):
                normalized = None
            if normalized is not None:
                monitors.append(normalized)
        return AirQualityStation(
            provider_station_id=station_id,
            name=name,
            short_name=_text(raw.get("shortName")),
            location={
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
            },
            city=_text(raw.get("city")),
            address=_text(raw.get("address")),
            provider_region_id=_provider_id(
                raw.get("regionId")
                if raw.get("regionId") is not None
                else fallback_region_id
            ),
            owner=_text(raw.get("owner")),
            active=raw.get("active") if isinstance(raw.get("active"), bool) else None,
            monitors=monitors,
        )

    def collect_latest(
        self, *, region_ids: Sequence[int] = tuple(range(16)), hours_back: int = 4
    ) -> AirQualityCollectionResult:
        collected_at = self.clock().astimezone(timezone.utc)
        if not region_ids or hours_back < 1:
            raise ValueError(
                "region_ids must not be empty and hours_back must be positive"
            )
        try:
            station_result = self.get_station_metadata()
        except MinistryAirQualityError as error:
            return AirQualityCollectionResult(
                status="failed", collected_at=collected_at, errors=[error.category]
            )
        station_map = {
            station.provider_station_id: station for station in station_result.stations
        }
        errors = list(station_result.errors)
        try:
            statuses = self.get_statuses()
            status_map = {
                str(item.get("Id")): str(item.get("Name"))
                for item in statuses
                if item.get("Id") is not None and item.get("Name") is not None
            }
        except MinistryAirQualityError as error:
            status_map = {}
            errors.append(f"status_metadata_{error.category}")
        try:
            payload = self._get_json(
                "regions/data/latest",
                params={
                    "unitConversion": "true",
                    "regionsIds": ",".join(str(item) for item in region_ids),
                    "hoursBack": hours_back,
                },
            )
        except MinistryAirQualityError as error:
            return AirQualityCollectionResult(
                status="failed",
                collected_at=collected_at,
                stations_considered=len(station_map),
                errors=[*errors, error.category],
            )
        if not isinstance(payload, list):
            return AirQualityCollectionResult(
                status="failed",
                collected_at=collected_at,
                stations_considered=len(station_map),
                errors=[*errors, "malformed_response"],
            )
        observations: list[AirQualityObservation] = []
        excluded: list[ExcludedAirQualityReading] = []
        for station_payload in payload:
            self._normalize_station_readings(
                station_payload, station_map, status_map, observations, excluded
            )
        partial = bool(errors or excluded or station_result.status == "partial")
        return AirQualityCollectionResult(
            status="partial" if partial else "success",
            collected_at=collected_at,
            observations=observations,
            excluded=excluded,
            stations_considered=len(station_map),
            errors=errors,
        )

    @classmethod
    def _normalize_station_readings(
        cls,
        raw: object,
        stations: Mapping[str, AirQualityStation],
        statuses: Mapping[str, str],
        observations: list[AirQualityObservation],
        excluded: list[ExcludedAirQualityReading],
    ) -> None:
        if not isinstance(raw, Mapping):
            excluded.append(ExcludedAirQualityReading(reason="malformed_channel"))
            return
        station_id = _provider_id(raw.get("stationId"))
        station = stations.get(station_id or "")
        region_data = raw.get("regionData")
        channels = (
            region_data.get("channels")
            if isinstance(region_data, Mapping)
            else None
        )
        if not isinstance(channels, list):
            excluded.append(
                ExcludedAirQualityReading(
                    reason="malformed_channel", provider_station_id=station_id
                )
            )
            return
        for channel in channels:
            if not isinstance(channel, Mapping):
                excluded.append(
                    ExcludedAirQualityReading(
                        reason="malformed_channel", provider_station_id=station_id
                    )
                )
                continue
            cls._normalize_channel(
                channel, station_id, station, statuses, observations, excluded
            )

    @classmethod
    def _normalize_channel(
        cls,
        channel: Mapping[str, Any],
        station_id: str | None,
        station: AirQualityStation | None,
        statuses: Mapping[str, str],
        observations: list[AirQualityObservation],
        excluded: list[ExcludedAirQualityReading],
    ) -> None:
        channel_id = _provider_id(_first_present(channel, "id", "channelId"))
        monitor = next(
            (
                item
                for item in (station.monitors if station is not None else [])
                if item.provider_channel_id == channel_id
            ),
            None,
        )
        raw_pollutant = _text(channel.get("name")) or (
            monitor.pollutant if monitor is not None else None
        )
        pollutant_id = _provider_id(channel.get("pollutantId")) or (
            monitor.provider_pollutant_id if monitor is not None else None
        )
        reading_unit = _text(channel.get("units"))
        metadata_unit = monitor.provider_unit if monitor is not None else None
        raw_unit = reading_unit or metadata_unit
        unit_source = "reading" if reading_unit else "metadata_fallback" if metadata_unit else "unknown"
        raw_timestamp = _text(channel.get("datetime"))
        raw_status = channel.get("status")
        status_id = _provider_id(raw_status)
        status_name = (
            statuses.get(status_id or "")
            or _text(channel.get("state"))
            or (
                _text(raw_status)
                if isinstance(raw_status, str) and not raw_status.isdigit()
                else None
            )
            or (monitor.provider_state if monitor is not None else None)
        )

        def reject(reason: str) -> None:
            excluded.append(
                ExcludedAirQualityReading(
                    reason=reason,
                    provider_station_id=station_id,
                    provider_channel_id=channel_id,
                    provider_pollutant=raw_pollutant,
                    provider_pollutant_id=pollutant_id,
                    provider_unit=raw_unit,
                    provider_timestamp=raw_timestamp,
                    provider_status_id=status_id,
                    provider_status=status_name,
                )
            )

        if station is None:
            reject("station_metadata_missing")
            return
        if station.active is False:
            reject("inactive_station")
            return
        pollutant = cls._canonical_pollutant(raw_pollutant)
        if pollutant is None:
            reject("unsupported_pollutant")
            return
        if channel.get("active") is False or (
            monitor is not None and monitor.active is False
        ):
            reject("inactive_channel")
            return
        if channel.get("valid") is not True:
            reject("provider_marked_invalid")
            return
        # The approved policy follows provider valid=True, preserving status as
        # evidence rather than applying a separate local status-name blacklist.
        value = channel.get("value")
        if isinstance(value, bool):
            reject("invalid_value")
            return
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            reject("invalid_value")
            return
        if numeric_value == INVALID_READING_SENTINEL:
            reject("invalid_sentinel")
            return
        if not math.isfinite(numeric_value):
            reject("invalid_value")
            return
        try:
            observed_at, provider_timestamp = _parse_provider_timestamp(raw_timestamp)
        except ValueError:
            reject("malformed_timestamp")
            return
        if channel_id is None:
            reject("malformed_channel")
            return
        try:
            observation = AirQualityObservation(
                provider_station_id=station.provider_station_id,
                provider_channel_id=channel_id,
                location=station.location,
                pollutant=pollutant,
                provider_pollutant_id=pollutant_id,
                value=numeric_value,
                unit=_canonical_unit(raw_unit),
                provider_unit=raw_unit,
                measurement_unit=_canonical_unit(reading_unit),
                reading_unit=channel.get("units") if reading_unit else None,
                metadata_unit=metadata_unit,
                unit_source=unit_source,
                quality_policy=LIVE_QUALITY_POLICY,
                observed_at=observed_at,
                provider_timestamp=provider_timestamp,
                provider_status_id=status_id,
                provider_status=status_name,
                source_id=f"station:{station.provider_station_id}",
            )
        except ValidationError as error:
            unit_error = any(
                item["loc"] and item["loc"][0] == "unit"
                for item in error.errors()
            )
            reject("unsupported_unit" if unit_error else "malformed_channel")
            return
        observations.append(observation)
