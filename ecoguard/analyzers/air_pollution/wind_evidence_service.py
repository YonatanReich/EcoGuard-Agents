"""Wind evidence for a pollution event, from stored readings first.

A stored reading costs nothing and is the one the event was actually built
from, so the provider is only asked when nothing usable is on hand - and what
comes back is kept, so the next event need not ask again."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from ecoguard.analyzers.air_pollution.transport_schemas import (
    WindEvidence,
    WindOriginalUnits,
)
from ecoguard.detectors.air_pollution.schemas import GeographicCoordinate

PERSISTED_WIND_SOURCES = ("weather", "ims_wind")


class PersistedFirstWindEvidenceService:
    """Read shared observations first, then use and persist the IMS fallback."""

    def __init__(
        self,
        live_service,
        *,
        reader: Callable[..., dict[str, Any] | None] | None = None,
        writer: Callable[[str, list[dict[str, Any]]], int] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """Build the service, wrapping the live one."""
        if reader is None:
            from ecoguard.database.repositories.weather_history import (
                wind_for_point_at,
            )

            reader = wind_for_point_at
        if writer is None:
            from ecoguard.database.repositories.observations import (
                upsert_observations,
            )

            writer = upsert_observations
        self._live_service = live_service
        self._reader = reader
        self._writer = writer
        self._clock = clock

    def select_wind_evidence(
        self,
        *,
        analysis_coordinates: GeographicCoordinate | Mapping[str, object],
        anomaly_observed_at: datetime,
        maximum_observation_age_seconds: float,
        alternative_limit: int = 3,
    ):
        """Wind evidence, from what is already stored where possible.

        A stored reading costs nothing and is what the event was built from, so the
        provider is only asked when nothing usable is on hand.
        """
        origin = GeographicCoordinate.model_validate(
            analysis_coordinates.model_dump()
            if isinstance(analysis_coordinates, GeographicCoordinate)
            else analysis_coordinates
        )
        anomaly_utc = self._utc(anomaly_observed_at, "anomaly_observed_at")
        maximum_age = self._positive_number(
            maximum_observation_age_seconds,
            "maximum_observation_age_seconds",
        )

        row = None
        try:
            row = self._reader(
                origin.latitude,
                origin.longitude,
                at=anomaly_utc,
                maximum_age_seconds=maximum_age,
                sources=PERSISTED_WIND_SOURCES,
            )
        except Exception:
            # A store outage is equivalent to a cache miss for selection.  A
            # successful live observation still must persist before use.
            row = None
        if row is not None:
            evidence = self._persisted_evidence(
                row,
                origin=origin,
                anomaly_observed_at=anomaly_utc,
                maximum_age_seconds=maximum_age,
            )
            if evidence is not None:
                return SimpleNamespace(wind_evidence=evidence)

        selection = self._live_service.select_wind_evidence(
            analysis_coordinates=origin,
            anomaly_observed_at=anomaly_utc,
            maximum_observation_age_seconds=maximum_age,
            alternative_limit=alternative_limit,
        )
        evidence = WindEvidence.model_validate(
            selection.wind_evidence.model_dump(round_trip=True)
        )
        self._persist_live_observation(evidence)
        return selection

    def _persisted_evidence(
        self,
        row: Mapping[str, Any],
        *,
        origin: GeographicCoordinate,
        anomaly_observed_at: datetime,
        maximum_age_seconds: float,
    ) -> WindEvidence | None:
        """One stored reading as wind evidence, or None when it is unusable."""
        try:
            observed_at = self._utc(row["observed_at"], "observed_at")
            age = (anomaly_observed_at - observed_at).total_seconds()
            if age < 0 or age > maximum_age_seconds:
                return None
            payload = row["payload"]
            if not isinstance(payload, Mapping):
                return None
            direction = self._direction(payload.get("wind_direction_10m"))
            raw_speed = self._nonnegative(payload.get("wind_speed_10m"))
            source = str(row["source"])
            speed_unit = str(payload.get("wind_speed_unit") or "km/h")
            speed = raw_speed if speed_unit == "m/s" else raw_speed / 3.6
            raw_gust = payload.get("wind_gusts_10m")
            gust = None if raw_gust is None else self._nonnegative(raw_gust)
            if gust is not None and speed_unit != "m/s":
                gust /= 3.6
            actual = GeographicCoordinate(
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
            )
            retrieved_at = self._utc(self._clock(), "clock")
            common = {
                "requested_coordinates": origin,
                "actual_provider_coordinates": actual,
                "raw_provider_timestamp": observed_at.isoformat(),
                "retrieved_at": retrieved_at,
                "wind_from_direction_deg": direction,
                "wind_speed_mps": speed,
                "gust_speed_mps": gust,
                "provider_validity": "valid",
                "provider_channel_validity": {
                    "wind_direction_10m": "valid",
                    "wind_speed_10m": "valid",
                },
                "time_offset_from_anomaly_seconds": -age,
                "metadata": {
                    "repository_source": source,
                    "distance_m": float(row["distance_m"]),
                    "maximum_observation_age_seconds": maximum_age_seconds,
                    "look_ahead_used": False,
                },
            }
            if source == "ims_wind":
                station_id = str(payload.get("provider_location_id") or row["cell_id"])
                return WindEvidence(
                    evidence_id=str(
                        payload.get("evidence_id")
                        or f"ims-wind:{station_id}:{observed_at.isoformat()}"
                    ),
                    provider=str(payload.get("provider") or "IMS"),
                    source_type="station_observation",
                    provider_location_kind="station",
                    provider_location_id=station_id,
                    provider_location_name=payload.get("provider_location_name"),
                    wind_observed_at=observed_at,
                    gust_from_direction_deg=payload.get("gust_from_direction_deg"),
                    direction_stddev_deg=payload.get("direction_stddev_deg"),
                    provider_status=payload.get("provider_status"),
                    original_units=WindOriginalUnits(
                        wind_direction=str(payload.get("wind_direction_unit") or "degrees"),
                        wind_speed=speed_unit,
                        gust_direction=(
                            str(payload.get("wind_direction_unit") or "degrees")
                            if payload.get("gust_from_direction_deg") is not None
                            else None
                        ),
                        gust_speed=(speed_unit if gust is not None else None),
                        direction_stddev=(
                            "degrees"
                            if payload.get("direction_stddev_deg") is not None
                            else None
                        ),
                    ),
                    reference=payload.get("reference"),
                    **common,
                )
            return WindEvidence(
                evidence_id=f"stored-weather:{row['cell_id']}:{observed_at.isoformat()}",
                provider="Open-Meteo",
                source_type="model_forecast",
                provider_location_kind="model_grid",
                provider_location_id=str(row["cell_id"]),
                provider_location_name="EcoGuard shared weather grid cell",
                wind_valid_at=observed_at,
                original_units=WindOriginalUnits(
                    wind_direction="degrees",
                    wind_speed="km/h",
                    gust_speed="km/h" if gust is not None else None,
                ),
                reference="observations:weather",
                **common,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _persist_live_observation(self, evidence: WindEvidence) -> None:
        """Keep a freshly fetched reading, so the next event need not fetch it again."""
        if evidence.source_type != "station_observation":
            raise RuntimeError("live_wind_is_not_an_observation")
        observed_at = evidence.wind_observed_at
        assert observed_at is not None
        payload = {
            "provider": evidence.provider,
            "evidence_id": evidence.evidence_id,
            "provider_location_id": evidence.provider_location_id,
            "provider_location_name": evidence.provider_location_name,
            "wind_direction_10m": evidence.wind_from_direction_deg,
            "wind_speed_10m": evidence.wind_speed_mps,
            "wind_gusts_10m": evidence.gust_speed_mps,
            "gust_from_direction_deg": evidence.gust_from_direction_deg,
            "direction_stddev_deg": evidence.direction_stddev_deg,
            "wind_direction_unit": "degrees",
            "wind_speed_unit": "m/s",
            "provider_status": evidence.provider_status,
            "provider_channel_validity": evidence.provider_channel_validity,
            "reference": evidence.reference,
            "retrieved_at": evidence.retrieved_at.isoformat(),
        }
        self._writer("ims_wind", [{
            "cell_id": f"ims:{evidence.provider_location_id}",
            "latitude": evidence.actual_provider_coordinates.latitude,
            "longitude": evidence.actual_provider_coordinates.longitude,
            "observed_at": observed_at,
            "payload": payload,
        }])

    @staticmethod
    def _utc(value: datetime, name: str) -> datetime:
        """A time in UTC, naming the field when it carries no timezone."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must carry a UTC offset")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _positive_number(value: object, name: str) -> float:
        """A value that must be a positive number, naming the field when it is not."""
        number = PersistedFirstWindEvidenceService._nonnegative(value)
        if number <= 0:
            raise ValueError(f"{name} must be positive")
        return number

    @staticmethod
    def _nonnegative(value: object) -> float:
        """A value that must not be negative."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("wind value must be numeric")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError("wind value must be finite and non-negative")
        return number

    @staticmethod
    def _direction(value: object) -> float:
        """A compass direction in degrees."""
        number = PersistedFirstWindEvidenceService._nonnegative(value)
        if number >= 360:
            raise ValueError("wind direction must be below 360")
        return number
