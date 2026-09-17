"""Read-only access to the shared PostGIS locality reference layer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ecoguard.database.engine import Session


class LocalityLookupStatus(StrEnum):
    SUCCESS_WITH_RESULTS = "SUCCESS_WITH_RESULTS"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    REFERENCE_DATA_NOT_LOADED = "REFERENCE_DATA_NOT_LOADED"
    UNAVAILABLE = "UNAVAILABLE"


class LocalityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    locality_code: str
    name_he: str
    name_en: str | None = None
    locality_type: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    distance_m: float = Field(ge=0)
    source: str | None = None
    source_resource_id: str | None = None
    source_updated_at: datetime | None = None
    imported_at: datetime | None = None
    source_version: str | None = None
    source_checksum: str | None = None
    raw_properties: dict[str, Any] | None = None


class LocalityLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: LocalityLookupStatus
    candidates: list[LocalityCandidate] = Field(default_factory=list)
    source: str = "shared_postgis_localities"
    reason: str | None = None


_LAYER_EXISTS_SQL = text(
    "SELECT to_regclass('public.localities') IS NOT NULL AS layer_exists"
)
_LAYER_POPULATED_SQL = text("SELECT EXISTS (SELECT 1 FROM localities LIMIT 1)")

_NEARBY_SQL = text(
    """
    WITH origin AS (
      SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326) AS point
    )
    SELECT
      locality_code,
      name_he,
      name_en,
      locality_type,
      ST_Y(representative_point) AS latitude,
      ST_X(representative_point) AS longitude,
      ST_Distance(representative_point::geography, origin.point::geography)
        AS distance_m,
      source,
      source_resource_id,
      source_updated_at,
      imported_at,
      source_version,
      source_checksum,
      raw_properties
    FROM localities, origin
    WHERE ST_DWithin(
      representative_point::geography,
      origin.point::geography,
      :radius_m
    )
    ORDER BY distance_m, locality_code
    """
)


def nearby_localities(
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
    session_factory=Session,
) -> LocalityLookupResult:
    """Return reference points near an event, preserving layer availability."""

    try:
        with session_factory() as session:
            layer_exists = session.execute(_LAYER_EXISTS_SQL).scalar_one()
            if not layer_exists:
                return LocalityLookupResult(
                    status=LocalityLookupStatus.REFERENCE_DATA_NOT_LOADED,
                    reason="reference_data_not_loaded",
                )
            if not session.execute(_LAYER_POPULATED_SQL).scalar_one():
                return LocalityLookupResult(
                    status=LocalityLookupStatus.REFERENCE_DATA_NOT_LOADED,
                    reason="reference_data_not_loaded",
                )
            rows = session.execute(
                _NEARBY_SQL,
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "radius_m": radius_m,
                },
            ).mappings().all()
    except (SQLAlchemyError, ValidationError, TypeError, ValueError):
        return LocalityLookupResult(
            status=LocalityLookupStatus.UNAVAILABLE,
            reason="locality_repository_unavailable",
        )

    candidates = [LocalityCandidate.model_validate(dict(row)) for row in rows]
    return LocalityLookupResult(
        status=(
            LocalityLookupStatus.SUCCESS_WITH_RESULTS
            if candidates
            else LocalityLookupStatus.SUCCESS_EMPTY
        ),
        candidates=candidates,
    )
