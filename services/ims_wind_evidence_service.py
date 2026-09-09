"""Normalize and select IMS observations for pollution transport screening.

IMS wind direction is measured meteorological ``wind from`` direction. This
module does not derive downwind geometry or invoke any transport calculation.
It corrects the documented IMS observation-clock defect by interpreting the
serialized wall time as fixed UTC+2, regardless of the offset printed by IMS.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from agents.air_pollution_anomaly_schemas import ContractModel, GeographicCoordinate
from agents.air_pollution_transport_schemas import WindEvidence, WindOriginalUnits
from services.air_pollution_transport_geometry import geodesic_distance_m
from services.ims_wind_observation_client import (
    IMSWindObservationClient,
    IMSWindObservationError,
)


IMS_FIXED_STANDARD_TIME = timezone(timedelta(hours=2))
REQUIRED_WIND_CHANNELS = ("WD", "WS")
OPTIONAL_WIND_CHANNELS = ("STDwd", "WDmax", "WSmax")
KNOWN_WIND_CHANNELS = REQUIRED_WIND_CHANNELS + OPTIONAL_WIND_CHANNELS
_CHANNEL_CANONICAL_NAMES = {name.casefold(): name for name in KNOWN_WIND_CHANNELS}
_EXPLICIT_INVALID_STATUS = {
    "2",
    "false",
    "incorrect",
    "invalid",
    "invld",
    "nodata",
    "no_data",
    "down",
    "calib",
    "calibration",
}


class IMSWindEvidenceError(RuntimeError):
    """A provider-evidence failure with no credential or response-body detail."""

    def __init__(
        self,
        category: str,
        *,
        diagnostics: Mapping[str, int] | None = None,
    ):
        super().__init__(category)
        self.category = category
        self.diagnostics = dict(diagnostics or {})


class IMSWindChannelMetadata(ContractModel):
    channel_id: str = Field(min_length=1, max_length=100)
    name: Literal["WD", "WS", "STDwd", "WDmax", "WSmax"]
    active: bool
    units: str = Field(min_length=1, max_length=100)
    type_id: str | None = Field(default=None, min_length=1, max_length=100)


class IMSWindStationMetadata(ContractModel):
    station_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    active: bool
    coordinates: GeographicCoordinate
    region_id: str | None = Field(default=None, min_length=1, max_length=100)
    region_name: str | None = Field(default=None, min_length=1, max_length=300)
    timebase_minutes: int | None = Field(default=None, gt=0, strict=True)
    channels: list[IMSWindChannelMetadata] = Field(default_factory=list)

    @model_validator(mode="after")
    def channel_identifiers_are_unique(self):
        identifiers = [channel.channel_id for channel in self.channels]
        names = [channel.name for channel in self.channels]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("station channel IDs must be unique")
        if len(set(names)) != len(names):
            raise ValueError("station wind channel names must be unique")
        return self

    def active_channel(self, name: str) -> IMSWindChannelMetadata | None:
        return next(
            (
                channel
                for channel in self.channels
                if channel.name == name and channel.active
            ),
            None,
        )

    @property
    def wind_capable(self) -> bool:
        return self.active and all(
            self.active_channel(name) is not None for name in REQUIRED_WIND_CHANNELS
        )


class IMSNormalizedWindObservation(ContractModel):
    raw_provider_timestamp: str = Field(min_length=1, max_length=200)
    observed_at: AwareDatetime
    aggregation_start: AwareDatetime | None = None
    aggregation_end: AwareDatetime | None = None
    wind_from_direction_deg: float = Field(ge=0, lt=360, strict=True)
    wind_speed_mps: float = Field(ge=0, strict=True)
    direction_stddev_deg: float | None = Field(default=None, ge=0, strict=True)
    gust_from_direction_deg: float | None = Field(default=None, ge=0, lt=360, strict=True)
    gust_speed_mps: float | None = Field(default=None, ge=0, strict=True)
    original_units: WindOriginalUnits
    channel_validity: dict[str, Literal["valid", "invalid", "unknown"]]
    provider_status: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("observed_at", "aggregation_start", "aggregation_end")
    @classmethod
    def normalize_times(cls, value: AwareDatetime | None):
        return value.astimezone(timezone.utc) if value is not None else None

    @model_validator(mode="after")
    def aggregation_is_coherent(self):
        if (self.aggregation_start is None) != (self.aggregation_end is None):
            raise ValueError("aggregation timestamps must be supplied together")
        if (
            self.aggregation_start is not None
            and self.aggregation_end is not None
            and self.aggregation_end < self.aggregation_start
        ):
            raise ValueError("aggregation end cannot precede start")
        return self


class IMSWindStationAlternative(ContractModel):
    station_id: str = Field(min_length=1, max_length=100)
    station_name: str = Field(min_length=1, max_length=300)
    station_distance_m: float = Field(ge=0, strict=True)
    wind_observed_at: AwareDatetime
    observation_age_seconds: float = Field(ge=0, strict=True)

    @field_validator("wind_observed_at")
    @classmethod
    def normalize_time(cls, value: AwareDatetime):
        return value.astimezone(timezone.utc)


class IMSWindSelectionDiagnostics(ContractModel):
    stations_considered: int = Field(ge=0, strict=True)
    stations_skipped_inactive: int = Field(ge=0, strict=True)
    stations_skipped_missing_required_wind_channels: int = Field(ge=0, strict=True)
    wind_capable_stations_queried: int = Field(ge=0, strict=True)
    station_days_without_data: int = Field(ge=0, strict=True)
    stations_skipped_no_daily_data: int = Field(ge=0, strict=True)
    stations_skipped_invalid_wind_observation: int = Field(ge=0, strict=True)
    stations_skipped_stale: int = Field(ge=0, strict=True)
    stations_skipped_future_only: int = Field(ge=0, strict=True)
    stations_skipped_unusable_response: int = Field(ge=0, strict=True)
    eligible_stations: int = Field(ge=0, strict=True)


class IMSWindEvidenceSelection(ContractModel):
    wind_evidence: WindEvidence
    station_distance_m: float = Field(ge=0, strict=True)
    observation_age_seconds: float = Field(ge=0, strict=True)
    selection_rationale: list[str] = Field(min_length=1)
    eligible_alternatives: list[IMSWindStationAlternative] = Field(default_factory=list)
    diagnostics: IMSWindSelectionDiagnostics

    @field_validator("selection_rationale")
    @classmethod
    def nonblank_rationale(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("selection rationale cannot contain blank entries")
        return stripped


def _text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_present(values: Mapping[str, Any], *keys: str) -> object | None:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return None


def _provider_id(value: object | None) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    return _text(value)


def _finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _canonical_channel_name(value: object | None) -> str | None:
    text = _text(value)
    return _CHANNEL_CANONICAL_NAMES.get(text.casefold()) if text else None


def _timebase_minutes(value: object | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value > 0 else None
    match = re.fullmatch(r"\s*(\d+)\s*(?:min(?:ute)?s?)?\s*", str(value), re.I)
    if not match:
        return None
    parsed = int(match.group(1))
    return parsed if parsed > 0 else None


def normalize_ims_observation_timestamp(raw_value: object) -> tuple[datetime, str]:
    """Interpret the IMS wall clock as fixed UTC+2 and return UTC plus raw text.

    IMS documents that the observation time is always Israel winter time even
    when its serialized offset says ``+03:00``. The printed offset is therefore
    deliberately ignored; the wall-clock fields are attached to fixed UTC+2.
    """

    raw = _text(raw_value)
    if raw is None:
        raise ValueError("IMS observation timestamp is missing")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("IMS observation timestamp is malformed") from None
    fixed_wall_time = parsed.replace(tzinfo=None).replace(tzinfo=IMS_FIXED_STANDARD_TIME)
    return fixed_wall_time.astimezone(timezone.utc), raw


def _station_records(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("stations", "data"):
            nested = payload.get(key)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                return [item for item in nested if isinstance(item, Mapping)]
        if _first_present(payload, "stationId", "id") is not None:
            return [payload]
    raise ValueError("IMS station metadata response is malformed")


def parse_ims_station_metadata(raw: object) -> IMSWindStationMetadata:
    if not isinstance(raw, Mapping):
        raise ValueError("IMS station metadata must be an object")
    station_id = _provider_id(_first_present(raw, "stationId", "id"))
    name = _text(_first_present(raw, "name", "stationName"))
    active = raw.get("active")
    location = raw.get("location")
    if station_id is None or name is None:
        raise ValueError("IMS station identity is missing")
    if not isinstance(active, bool):
        raise ValueError("IMS station active state is missing")
    if not isinstance(location, Mapping):
        raise ValueError("IMS station location is missing")

    channels: list[IMSWindChannelMetadata] = []
    raw_monitors = _first_present(raw, "monitors", "channels")
    if raw_monitors is not None:
        if not isinstance(raw_monitors, Sequence) or isinstance(raw_monitors, (str, bytes)):
            raise ValueError("IMS station monitor inventory is malformed")
        for monitor in raw_monitors:
            if not isinstance(monitor, Mapping):
                continue
            channel_name = _canonical_channel_name(monitor.get("name"))
            if channel_name is None:
                continue
            channel_id = _provider_id(_first_present(monitor, "channelId", "id"))
            units = _text(_first_present(monitor, "units", "unit"))
            channel_active = monitor.get("active")
            if channel_id is None or units is None or not isinstance(channel_active, bool):
                raise ValueError("IMS wind monitor metadata is incomplete")
            channels.append(
                IMSWindChannelMetadata(
                    channel_id=channel_id,
                    name=channel_name,
                    active=channel_active,
                    units=units,
                    type_id=_provider_id(_first_present(monitor, "typeId", "type_id")),
                )
            )

    region_value = raw.get("region")
    region_name = (
        _text(region_value.get("name"))
        if isinstance(region_value, Mapping)
        else _text(raw.get("regionName"))
    )
    return IMSWindStationMetadata(
        station_id=station_id,
        name=name,
        active=active,
        coordinates=GeographicCoordinate(
            latitude=_finite_number(location.get("latitude"), field_name="latitude"),
            longitude=_finite_number(location.get("longitude"), field_name="longitude"),
        ),
        region_id=_provider_id(_first_present(raw, "regionId", "region_id")),
        region_name=region_name,
        timebase_minutes=_timebase_minutes(
            _first_present(raw, "timebase", "timeBase", "timebaseMinutes")
        ),
        channels=channels,
    )


def _observation_records(payload: object) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []

    def visit(value: object) -> None:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                visit(item)
            return
        if not isinstance(value, Mapping):
            return
        channel_values = _first_present(value, "channels", "values")
        timestamp = _first_present(value, "datetime", "dateTime", "timestamp")
        if timestamp is not None and isinstance(channel_values, Sequence):
            records.append(value)
            return
        for key in ("data", "observations", "stationData"):
            if key in value:
                visit(value[key])

    visit(payload)
    if not records:
        raise ValueError("IMS observation response contains no observation records")
    return records


def _status_is_acceptable(value: object | None) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(float(value)) and float(value) == 1.0
    normalized = str(value).strip().casefold()
    if normalized in _EXPLICIT_INVALID_STATUS:
        return False
    return normalized in {"1", "true", "correct", "valid", "normal", "ok"}


def _direction_degrees(value: object, unit: str, *, field_name: str) -> float:
    normalized_unit = unit.strip().casefold().replace(" ", "")
    if normalized_unit not in {"deg", "degree", "degrees", "°"}:
        raise ValueError(f"unsupported {field_name} unit")
    result = _finite_number(value, field_name=field_name)
    if not 0 <= result < 360:
        raise ValueError(f"{field_name} must satisfy 0 <= degrees < 360")
    return result


def _nonnegative_degrees(value: object, unit: str, *, field_name: str) -> float:
    normalized_unit = unit.strip().casefold().replace(" ", "")
    if normalized_unit not in {"deg", "degree", "degrees", "°"}:
        raise ValueError(f"unsupported {field_name} unit")
    result = _finite_number(value, field_name=field_name)
    if result < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return result


def _speed_mps(value: object, unit: str, *, field_name: str) -> float:
    result = _finite_number(value, field_name=field_name)
    if result < 0:
        raise ValueError(f"{field_name} cannot be negative")
    normalized_unit = (
        unit.strip().casefold().replace(" ", "").replace("per", "/")
    )
    if normalized_unit in {"m/s", "m/sec", "mps", "ms-1", "m/s-1"}:
        return result
    if normalized_unit in {"km/h", "km/hr", "kmh", "kph"}:
        return result / 3.6
    raise ValueError(f"unsupported {field_name} unit")


def _resolved_channel_values(
    raw_record: Mapping[str, Any],
    station: IMSWindStationMetadata,
) -> dict[str, Mapping[str, Any]]:
    raw_channels = _first_present(raw_record, "channels", "values")
    if not isinstance(raw_channels, Sequence) or isinstance(raw_channels, (str, bytes)):
        raise ValueError("IMS observation channel list is malformed")
    by_id = {channel.channel_id: channel for channel in station.channels}
    by_name = {channel.name: channel for channel in station.channels}
    resolved: dict[str, Mapping[str, Any]] = {}
    for raw_channel in raw_channels:
        if not isinstance(raw_channel, Mapping):
            continue
        raw_id = _provider_id(_first_present(raw_channel, "id", "channelId"))
        raw_name = _canonical_channel_name(raw_channel.get("name"))
        metadata = by_id.get(raw_id) if raw_id is not None else None
        if metadata is None and raw_name is not None:
            metadata = by_name.get(raw_name)
        if metadata is None or not metadata.active:
            continue
        if raw_name is not None and raw_name != metadata.name:
            continue
        resolved[metadata.name] = raw_channel
    return resolved


def _valid_channel_value(
    channels: Mapping[str, Mapping[str, Any]],
    metadata: IMSWindChannelMetadata,
    *,
    required: bool,
) -> tuple[object, str | None] | None:
    raw = channels.get(metadata.name)
    if raw is None:
        if required:
            raise ValueError(f"required IMS channel {metadata.name} is missing")
        return None
    if raw.get("valid") is not True:
        if required:
            raise ValueError(f"required IMS channel {metadata.name} is invalid")
        return None
    status = raw.get("status")
    if not _status_is_acceptable(status):
        if required:
            raise ValueError(f"required IMS channel {metadata.name} status is invalid")
        return None
    value = raw.get("value")
    if value is None:
        if required:
            raise ValueError(f"required IMS channel {metadata.name} has no value")
        return None
    return value, _text(status)


def normalize_ims_wind_observation(
    raw_record: object,
    station: IMSWindStationMetadata,
) -> IMSNormalizedWindObservation:
    if not station.wind_capable:
        raise ValueError("station is not active with active WD and WS channels")
    if not isinstance(raw_record, Mapping):
        raise ValueError("IMS observation record must be an object")
    observed_at, raw_timestamp = normalize_ims_observation_timestamp(
        _first_present(raw_record, "datetime", "dateTime", "timestamp")
    )
    resolved = _resolved_channel_values(raw_record, station)
    metadata = {channel.name: channel for channel in station.channels}

    wd_raw, wd_status = _valid_channel_value(
        resolved, metadata["WD"], required=True
    ) or (None, None)
    ws_raw, ws_status = _valid_channel_value(
        resolved, metadata["WS"], required=True
    ) or (None, None)
    wind_direction = _direction_degrees(
        wd_raw, metadata["WD"].units, field_name="wind_from_direction_deg"
    )
    wind_speed = _speed_mps(
        ws_raw, metadata["WS"].units, field_name="wind_speed_mps"
    )

    optional_values: dict[str, float | None] = {
        "STDwd": None,
        "WDmax": None,
        "WSmax": None,
    }
    optional_status: dict[str, str | None] = {}
    for name in OPTIONAL_WIND_CHANNELS:
        channel_metadata = metadata.get(name)
        if channel_metadata is None or not channel_metadata.active:
            continue
        item = _valid_channel_value(resolved, channel_metadata, required=False)
        if item is None:
            continue
        raw_value, status = item
        if name == "STDwd":
            optional_values[name] = _nonnegative_degrees(
                raw_value, channel_metadata.units, field_name="direction_stddev_deg"
            )
        elif name == "WDmax":
            optional_values[name] = _direction_degrees(
                raw_value, channel_metadata.units, field_name="gust_from_direction_deg"
            )
        else:
            optional_values[name] = _speed_mps(
                raw_value, channel_metadata.units, field_name="gust_speed_mps"
            )
        optional_status[name] = status

    aggregation_end = observed_at if station.timebase_minutes is not None else None
    aggregation_start = (
        observed_at - timedelta(minutes=station.timebase_minutes)
        if station.timebase_minutes is not None
        else None
    )
    channel_validity = {
        name: ("valid" if name in resolved and (
            name in REQUIRED_WIND_CHANNELS or optional_values.get(name) is not None
        ) else "unknown")
        for name in KNOWN_WIND_CHANNELS
    }
    statuses = {"WD": wd_status, "WS": ws_status, **optional_status}
    status_text = "; ".join(
        f"{name}={status if status is not None else 'unspecified'}"
        for name, status in statuses.items()
    )
    return IMSNormalizedWindObservation(
        raw_provider_timestamp=raw_timestamp,
        observed_at=observed_at,
        aggregation_start=aggregation_start,
        aggregation_end=aggregation_end,
        wind_from_direction_deg=wind_direction,
        wind_speed_mps=wind_speed,
        direction_stddev_deg=optional_values["STDwd"],
        gust_from_direction_deg=optional_values["WDmax"],
        gust_speed_mps=optional_values["WSmax"],
        original_units=WindOriginalUnits(
            wind_direction=metadata["WD"].units,
            wind_speed=metadata["WS"].units,
            direction_stddev=(
                metadata["STDwd"].units
                if optional_values["STDwd"] is not None
                else None
            ),
            gust_direction=(
                metadata["WDmax"].units
                if optional_values["WDmax"] is not None
                else None
            ),
            gust_speed=(
                metadata["WSmax"].units
                if optional_values["WSmax"] is not None
                else None
            ),
        ),
        channel_validity=channel_validity,
        provider_status=status_text,
    )


def parse_ims_wind_observations(
    payload: object,
    station: IMSWindStationMetadata,
) -> list[IMSNormalizedWindObservation]:
    observations: list[IMSNormalizedWindObservation] = []
    for record in _observation_records(payload):
        try:
            observations.append(normalize_ims_wind_observation(record, station))
        except (TypeError, ValueError):
            continue
    return sorted(observations, key=lambda observation: observation.observed_at)


class IMSWindEvidenceService:
    """Retrieve and select one non-look-ahead station observation.

    Eligibility is a hard filter: active station, active WD/WS metadata,
    valid observations, no future timestamp, and caller-supplied maximum age.
    Remaining candidates sort by station distance, observation age, then stable
    station ID. No stations are averaged and no instrument-siting quality is
    invented when IMS metadata does not provide it.
    """

    def __init__(
        self,
        client: IMSWindObservationClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.client = client
        self.clock = clock

    def discover_stations(
        self, payload: object | None = None
    ) -> list[IMSWindStationMetadata]:
        """Parse station metadata, fetching station detail only when needed."""

        parsed: list[IMSWindStationMetadata] = []
        station_payload = self.client.get_stations() if payload is None else payload
        for raw in _station_records(station_payload):
            detail = raw
            monitors = _first_present(raw, "monitors", "channels")
            station_id = _provider_id(_first_present(raw, "stationId", "id"))
            if monitors is None and station_id is not None:
                try:
                    detail_payload = self.client.get_station(station_id)
                    detail_records = _station_records(detail_payload)
                except (TypeError, ValueError):
                    continue
                if not detail_records:
                    continue
                detail = detail_records[0]
            try:
                parsed.append(parse_ims_station_metadata(detail))
            except (TypeError, ValueError):
                continue
        return parsed

    def _observation_payload(
        self,
        station_id: str,
        start_wall: datetime,
        end_wall: datetime,
    ) -> tuple[list[object], int, list[IMSWindObservationError]]:
        """Fetch documented daily resources covering the bounded evidence window.

        Daily resources avoid depending on the historically ambiguous range-query
        spelling. At most one request is made per calendar day in the caller's
        explicit observation-age window.
        """

        payloads: list[object] = []
        no_data_days = 0
        unusable_responses: list[IMSWindObservationError] = []
        day = start_wall.date()
        end_day = end_wall.date()
        while day <= end_day:
            try:
                payloads.append(self.client.get_station_data_daily(station_id, day))
            except IMSWindObservationError as error:
                if error.category in {"empty_response", "not_found"}:
                    no_data_days += 1
                elif error.category in {"invalid_json", "unsupported_response_shape"}:
                    unusable_responses.append(error)
                else:
                    raise
            day += timedelta(days=1)
        return payloads, no_data_days, unusable_responses

    def select_wind_evidence(
        self,
        *,
        analysis_coordinates: GeographicCoordinate | Mapping[str, object],
        anomaly_observed_at: datetime,
        maximum_observation_age_seconds: float,
        alternative_limit: int = 3,
    ) -> IMSWindEvidenceSelection:
        origin = GeographicCoordinate.model_validate(
            analysis_coordinates.model_dump()
            if isinstance(analysis_coordinates, GeographicCoordinate)
            else analysis_coordinates
        )
        if anomaly_observed_at.tzinfo is None or anomaly_observed_at.utcoffset() is None:
            raise ValueError("anomaly_observed_at must be timezone-aware")
        anomaly_utc = anomaly_observed_at.astimezone(timezone.utc)
        maximum_age = _finite_number(
            maximum_observation_age_seconds,
            field_name="maximum_observation_age_seconds",
        )
        if maximum_age <= 0:
            raise ValueError("maximum_observation_age_seconds must be positive")
        if isinstance(alternative_limit, bool) or not isinstance(alternative_limit, int):
            raise ValueError("alternative_limit must be a non-negative integer")
        if alternative_limit < 0:
            raise ValueError("alternative_limit must be a non-negative integer")

        start_wall = (anomaly_utc - timedelta(seconds=maximum_age)).astimezone(
            IMS_FIXED_STANDARD_TIME
        )
        end_wall = anomaly_utc.astimezone(IMS_FIXED_STANDARD_TIME)
        candidates: list[
            tuple[
                float,
                float,
                str,
                IMSWindStationMetadata,
                IMSNormalizedWindObservation,
            ]
        ] = []
        stations = self.discover_stations()
        diagnostic_counts = {
            "stations_considered": len(stations),
            "stations_skipped_inactive": 0,
            "stations_skipped_missing_required_wind_channels": 0,
            "wind_capable_stations_queried": 0,
            "station_days_without_data": 0,
            "stations_skipped_no_daily_data": 0,
            "stations_skipped_invalid_wind_observation": 0,
            "stations_skipped_stale": 0,
            "stations_skipped_future_only": 0,
            "stations_skipped_unusable_response": 0,
            "eligible_stations": 0,
        }
        wind_capable: list[tuple[float, str, IMSWindStationMetadata]] = []
        for station in stations:
            if not station.active:
                diagnostic_counts["stations_skipped_inactive"] += 1
                continue
            if not all(
                station.active_channel(name) is not None
                for name in REQUIRED_WIND_CHANNELS
            ):
                diagnostic_counts[
                    "stations_skipped_missing_required_wind_channels"
                ] += 1
                continue
            wind_capable.append(
                (
                    geodesic_distance_m(origin, station.coordinates),
                    station.station_id,
                    station,
                )
            )
        wind_capable.sort(key=lambda item: (item[0], item[1]))
        unusable_response_errors: list[IMSWindObservationError] = []
        for distance, _, station in wind_capable:
            diagnostic_counts["wind_capable_stations_queried"] += 1
            payload, no_data_days, unusable_responses = self._observation_payload(
                station.station_id, start_wall, end_wall
            )
            diagnostic_counts["station_days_without_data"] += no_data_days
            if unusable_responses:
                diagnostic_counts["stations_skipped_unusable_response"] += 1
                unusable_response_errors.extend(unusable_responses)
            if not payload:
                if not unusable_responses:
                    diagnostic_counts["stations_skipped_no_daily_data"] += 1
                continue
            try:
                observations = parse_ims_wind_observations(payload, station)
            except (TypeError, ValueError):
                diagnostic_counts["stations_skipped_no_daily_data"] += 1
                continue
            if not observations:
                diagnostic_counts["stations_skipped_invalid_wind_observation"] += 1
                continue
            eligible = [
                observation
                for observation in observations
                if observation.observed_at <= anomaly_utc
                and (anomaly_utc - observation.observed_at).total_seconds()
                <= maximum_age
            ]
            if not eligible:
                if all(observation.observed_at > anomaly_utc for observation in observations):
                    diagnostic_counts["stations_skipped_future_only"] += 1
                else:
                    diagnostic_counts["stations_skipped_stale"] += 1
                continue
            observation = max(eligible, key=lambda item: item.observed_at)
            age = (anomaly_utc - observation.observed_at).total_seconds()
            candidates.append((distance, age, station.station_id, station, observation))
            diagnostic_counts["eligible_stations"] += 1

        if not candidates:
            if (
                unusable_response_errors
                and diagnostic_counts["stations_skipped_unusable_response"]
                == diagnostic_counts["wind_capable_stations_queried"]
            ):
                raise unusable_response_errors[0]
            raise IMSWindEvidenceError(
                "no_eligible_wind_observation",
                diagnostics=diagnostic_counts,
            )
        selection_diagnostics = IMSWindSelectionDiagnostics(**diagnostic_counts)
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        distance, age, _, station, observation = candidates[0]
        alternatives = [
            IMSWindStationAlternative(
                station_id=item[3].station_id,
                station_name=item[3].name,
                station_distance_m=item[0],
                wind_observed_at=item[4].observed_at,
                observation_age_seconds=item[1],
            )
            for item in candidates[1 : 1 + alternative_limit]
        ]
        rationale = [
            "active IMS station with active WD and WS channels",
            "required channel values are provider-valid and status-valid",
            "observation ends at or before the anomaly timestamp",
            f"observation age is within caller limit of {maximum_age:g} seconds",
            "eligible stations ordered by distance, then observation age, then station ID",
            "station elevation and instrument-siting representativeness were not available for ranking",
            "no multi-station directional averaging was performed",
        ]
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at clock must return a timezone-aware timestamp")
        retrieved_at = retrieved_at.astimezone(timezone.utc)
        metadata: dict[str, JsonValue] = {
            "station_distance_m": distance,
            "station_region_id": station.region_id,
            "station_region_name": station.region_name,
            "station_timebase_minutes": station.timebase_minutes,
            "selection_rationale": rationale,
            "eligible_alternatives": [item.model_dump(mode="json") for item in alternatives],
            "maximum_observation_age_seconds": maximum_age,
            "timestamp_normalization": "IMS fixed UTC+2 wall time converted to UTC",
            "look_ahead_used": False,
            "selection_diagnostics": selection_diagnostics.model_dump(mode="json"),
        }
        evidence = WindEvidence(
            evidence_id=(
                f"ims-wind:{station.station_id}:"
                f"{observation.observed_at.isoformat()}"
            ),
            provider="IMS",
            source_type="station_observation",
            provider_location_kind="station",
            provider_location_id=station.station_id,
            provider_location_name=station.name,
            requested_coordinates=origin,
            actual_provider_coordinates=station.coordinates,
            raw_provider_timestamp=observation.raw_provider_timestamp,
            wind_observed_at=observation.observed_at,
            retrieved_at=retrieved_at,
            wind_aggregation_start=observation.aggregation_start,
            wind_aggregation_end=observation.aggregation_end,
            wind_from_direction_deg=observation.wind_from_direction_deg,
            wind_speed_mps=observation.wind_speed_mps,
            gust_from_direction_deg=observation.gust_from_direction_deg,
            gust_speed_mps=observation.gust_speed_mps,
            direction_stddev_deg=observation.direction_stddev_deg,
            provider_validity="valid",
            provider_status=observation.provider_status,
            provider_channel_validity=observation.channel_validity,
            original_units=observation.original_units,
            time_offset_from_anomaly_seconds=-age,
            reference=self.client.station_data_reference(station.station_id),
            metadata=metadata,
        )
        return IMSWindEvidenceSelection(
            wind_evidence=evidence,
            station_distance_m=distance,
            observation_age_seconds=age,
            selection_rationale=rationale,
            eligible_alternatives=alternatives,
            diagnostics=selection_diagnostics,
        )
