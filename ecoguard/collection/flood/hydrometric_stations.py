"""Water Authority hydrometric station reference-data ingestion.

The catalog is semi-static. This module exposes an idempotent one-shot loader;
it does not schedule itself. A caller decides when a refresh is appropriate.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from sqlalchemy import text

from ecoguard.collection.flood.hydrology_static import (
    BASE_URL,
    REQUEST_TIMEOUT_SECONDS,
)
from ecoguard.collection.base import cell_for


SOURCE = "water_authority_hydrometric_stations"
CATALOG_PATH = "/db_requests/get_hydro_stations_A7f3Q.php"
USER_AGENT = "Mozilla/5.0 (compatible; EcoGuard-Agents/1.0)"
TOKEN_PATTERN = re.compile(
    r'<meta\s+name=["\']api-token["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
RETURN_PERIODS = (2, 5, 10, 20, 50, 100)
MISSING_THRESHOLD = 999.0
FLOW_THRESHOLD_STATUS_COMPLETE = "complete_thresholds"
FLOW_THRESHOLD_STATUS_MISSING = "missing_thresholds"
FLOW_THRESHOLD_STATUS_PARTIAL = "partial_thresholds"


class HydrometricStationCatalogError(ValueError):
    """The station endpoint returned an unsafe or unexpected catalog."""


@dataclass(frozen=True)
class HydrometricStationCatalog:
    source_url: str
    source_version: str
    checksum: str
    owners: list[dict[str, Any]]
    stations: list[dict[str, Any]]
    rain_links: list[dict[str, Any]]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HydrometricStationCatalogError(f"{label} must be an object")
    return value


def _required_int(value: Any, label: str) -> int:
    if value is None or isinstance(value, bool):
        raise HydrometricStationCatalogError(f"{label} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise HydrometricStationCatalogError(f"{label} must be an integer") from error


def _optional_int(value: Any, label: str) -> int | None:
    return None if value is None else _required_int(value, label)


def _required_float(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise HydrometricStationCatalogError(f"{label} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise HydrometricStationCatalogError(f"{label} must be numeric") from error


def _optional_float(value: Any, label: str) -> float | None:
    return None if value is None else _required_float(value, label)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _threshold(value: Any, label: str) -> float | None:
    number = _required_float(value, label)
    if number == MISSING_THRESHOLD:
        return None
    if number < 0:
        raise HydrometricStationCatalogError(f"{label} cannot be negative")
    return number


def _flow_threshold_status(thresholds: list[float | None]) -> str:
    """Classify the complete rating curve once, at the source boundary."""
    available = sum(value is not None for value in thresholds)
    if available == len(RETURN_PERIODS):
        return FLOW_THRESHOLD_STATUS_COMPLETE
    if available == 0:
        return FLOW_THRESHOLD_STATUS_MISSING
    return FLOW_THRESHOLD_STATUS_PARTIAL


def parse_hydrometric_station_catalog(
    response: Any,
    *,
    synced_at: datetime | None = None,
) -> HydrometricStationCatalog:
    """Validate the endpoint response and produce normalized database rows."""
    if not isinstance(response, list) or len(response) < 2:
        raise HydrometricStationCatalogError("station response must contain stations and owners")

    raw_stations = _required_mapping(response[0], "stations")
    raw_owners = _required_mapping(response[1], "owners")
    if not raw_stations:
        raise HydrometricStationCatalogError("station response contains no stations")
    if not raw_owners:
        raise HydrometricStationCatalogError("station response contains no owners")

    synced_at = synced_at or datetime.now(timezone.utc)
    owners: list[dict[str, Any]] = []
    owner_ids: set[int] = set()
    for source_id, raw_owner in raw_owners.items():
        owner = _required_mapping(raw_owner, f"owner {source_id}")
        source_owner_id = _required_int(source_id, "owner id")
        name = _optional_text(owner.get("name"))
        if name is None:
            raise HydrometricStationCatalogError(f"owner {source_owner_id} has no name")
        owner_ids.add(source_owner_id)
        owners.append({
            "source_owner_id": source_owner_id,
            "owner_code": _optional_text(owner.get("owner_code")),
            "name": name,
            "source_metadata": _canonical_json(owner),
            "synced_at": synced_at,
        })

    stations: list[dict[str, Any]] = []
    rain_links: list[dict[str, Any]] = []
    station_ids: set[int] = set()
    for source_id, raw_station in raw_stations.items():
        station = _required_mapping(raw_station, f"station {source_id}")
        source_station_id = _required_int(source_id, "station id")
        if source_station_id in station_ids:
            raise HydrometricStationCatalogError(
                f"duplicate station id {source_station_id}"
            )
        station_ids.add(source_station_id)

        owner_source_id = _required_int(
            station.get("owner_id"), f"station {source_station_id} owner_id"
        )
        if owner_source_id not in owner_ids:
            raise HydrometricStationCatalogError(
                f"station {source_station_id} references unknown owner {owner_source_id}"
            )

        thresholds = station.get("threshold")
        if not isinstance(thresholds, list) or len(thresholds) != len(RETURN_PERIODS):
            raise HydrometricStationCatalogError(
                f"station {source_station_id} must have six discharge thresholds"
            )
        normalized_thresholds = [
            _threshold(value, f"station {source_station_id} threshold {period}y")
            for value, period in zip(thresholds, RETURN_PERIODS)
        ]
        flow_threshold_status = _flow_threshold_status(normalized_thresholds)

        name_he = _optional_text(station.get("name_he"))
        name_en = _optional_text(station.get("name_en"))
        if name_he is None and name_en is None:
            raise HydrometricStationCatalogError(f"station {source_station_id} has no name")

        stations.append({
            "source_station_id": source_station_id,
            "name_he": name_he,
            "name_en": name_en,
            "latitude": _required_float(
                station.get("lat"), f"station {source_station_id} latitude"
            ),
            "longitude": _required_float(
                station.get("lon"), f"station {source_station_id} longitude"
            ),
            "owner_source_id": owner_source_id,
            "map_zoom_level": _optional_int(
                station.get("zoom"), f"station {source_station_id} zoom"
            ),
            # Negative values are valid because water levels are relative to a
            # station datum, not to sea level or the river bed.
            "flow_start_water_level_m": _optional_float(
                station.get("level_flow_start"),
                f"station {source_station_id} level_flow_start",
            ),
            **{
                f"flow_threshold_{period}y_m3s": value
                for period, value in zip(RETURN_PERIODS, normalized_thresholds)
            },
            "flow_threshold_status": flow_threshold_status,
            "source_metadata": _canonical_json(station),
            "synced_at": synced_at,
        })

        envista_ids = station.get("envista_id")
        if not isinstance(envista_ids, list) or len(envista_ids) > 4:
            raise HydrometricStationCatalogError(
                f"station {source_station_id} envista_id must be an array of up to four ids"
            )
        seen_rain_ids: set[int] = set()
        for link_order, raw_rain_id in enumerate(envista_ids, start=1):
            if raw_rain_id is None:
                continue
            rain_station_source_id = _required_int(
                raw_rain_id, f"station {source_station_id} envista_id"
            )
            if rain_station_source_id in seen_rain_ids:
                raise HydrometricStationCatalogError(
                    f"station {source_station_id} repeats rain station {rain_station_source_id}"
                )
            seen_rain_ids.add(rain_station_source_id)
            rain_links.append({
                "hydrometric_station_source_id": source_station_id,
                "rain_station_source_id": rain_station_source_id,
                "link_order": link_order,
                "synced_at": synced_at,
            })

    catalog_payload = {"stations": raw_stations, "owners": raw_owners}
    checksum = hashlib.sha256(_canonical_json(catalog_payload).encode("utf-8")).hexdigest()
    return HydrometricStationCatalog(
        source_url=f"{BASE_URL}{CATALOG_PATH}",
        source_version=CATALOG_PATH.rsplit("/", 1)[-1],
        checksum=checksum,
        owners=owners,
        stations=stations,
        rain_links=rain_links,
    )


def fetch_hydrometric_station_catalog(
    http_session: requests.Session | None = None,
    *,
    language: str = "he",
) -> HydrometricStationCatalog:
    """Create a permitted page session, then retrieve the station catalog."""
    http = http_session or requests.Session()
    page_url = f"{BASE_URL}/index.php/?page=hydro_obs&lang={language}"
    page_response = http.get(
        page_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    page_response.raise_for_status()
    token_match = TOKEN_PATTERN.search(page_response.text)
    if token_match is None:
        raise HydrometricStationCatalogError("map page did not provide a session token")

    response = http.post(
        f"{BASE_URL}{CATALOG_PATH}",
        data={"lang": language},
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Referer": page_url,
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "X-SESSION-TOKEN": token_match.group(1),
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except requests.JSONDecodeError as error:
        raise HydrometricStationCatalogError("station endpoint returned invalid JSON") from error
    return parse_hydrometric_station_catalog(payload)


OWNER_UPSERT = text(
    """
    INSERT INTO water_authority_station_owners
      (source_owner_id, owner_code, name, is_active, source_metadata, synced_at)
    VALUES
      (:source_owner_id, :owner_code, :name, true, CAST(:source_metadata AS jsonb), :synced_at)
    ON CONFLICT ON CONSTRAINT water_authority_station_owners_identity DO UPDATE SET
      owner_code = EXCLUDED.owner_code,
      name = EXCLUDED.name,
      is_active = true,
      source_metadata = EXCLUDED.source_metadata,
      synced_at = EXCLUDED.synced_at
    """
)

STATION_UPSERT = text(
    """
    INSERT INTO hydrometric_stations
      (source_station_id, name_he, name_en, location, cell_id, owner_id, map_zoom_level,
       flow_start_water_level_m, flow_threshold_2y_m3s, flow_threshold_5y_m3s,
       flow_threshold_10y_m3s, flow_threshold_20y_m3s, flow_threshold_50y_m3s,
       flow_threshold_100y_m3s, flow_threshold_status, is_active,
       source_metadata, synced_at)
    VALUES
      (:source_station_id, :name_he, :name_en,
       ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
       :cell_id, :owner_id, :map_zoom_level, :flow_start_water_level_m,
       :flow_threshold_2y_m3s, :flow_threshold_5y_m3s,
       :flow_threshold_10y_m3s, :flow_threshold_20y_m3s,
       :flow_threshold_50y_m3s, :flow_threshold_100y_m3s,
       :flow_threshold_status,
       true, CAST(:source_metadata AS jsonb), :synced_at)
    ON CONFLICT ON CONSTRAINT hydrometric_stations_identity DO UPDATE SET
      name_he = EXCLUDED.name_he,
      name_en = EXCLUDED.name_en,
      location = EXCLUDED.location,
      cell_id = EXCLUDED.cell_id,
      owner_id = EXCLUDED.owner_id,
      map_zoom_level = EXCLUDED.map_zoom_level,
      flow_start_water_level_m = EXCLUDED.flow_start_water_level_m,
      flow_threshold_2y_m3s = EXCLUDED.flow_threshold_2y_m3s,
      flow_threshold_5y_m3s = EXCLUDED.flow_threshold_5y_m3s,
      flow_threshold_10y_m3s = EXCLUDED.flow_threshold_10y_m3s,
      flow_threshold_20y_m3s = EXCLUDED.flow_threshold_20y_m3s,
      flow_threshold_50y_m3s = EXCLUDED.flow_threshold_50y_m3s,
      flow_threshold_100y_m3s = EXCLUDED.flow_threshold_100y_m3s,
      flow_threshold_status = EXCLUDED.flow_threshold_status,
      is_active = true,
      source_metadata = EXCLUDED.source_metadata,
      synced_at = EXCLUDED.synced_at
    """
)

LINK_INSERT = text(
    """
    INSERT INTO hydrometric_station_rain_links
      (hydrometric_station_id, rain_station_source_id, link_order, synced_at)
    VALUES
      (:hydrometric_station_id, :rain_station_source_id, :link_order, :synced_at)
    """
)


def persist_hydrometric_station_catalog(
    catalog: HydrometricStationCatalog,
) -> dict[str, int]:
    """Idempotently synchronize owners, stations and rain-station links."""
    from ecoguard.database.engine import Session

    checked_at = datetime.now(timezone.utc)
    with Session() as session:
        existing_checksum = session.execute(
            text(
                "SELECT content_sha256 FROM static_layer_imports "
                "WHERE layer_name = 'hydrometric_stations'"
            )
        ).scalar_one_or_none()
        if existing_checksum == catalog.checksum:
            session.execute(
                text(
                    "UPDATE static_layer_imports SET checked_at = :checked_at "
                    "WHERE layer_name = 'hydrometric_stations'"
                ),
                {"checked_at": checked_at},
            )
            session.commit()
            return {"owners": 0, "stations": 0, "rain_links": 0}

        # Rows absent from the newest catalog stay available for historical
        # references but are no longer eligible for current-station queries.
        session.execute(text("UPDATE water_authority_station_owners SET is_active = false"))
        session.execute(text("UPDATE hydrometric_stations SET is_active = false"))
        session.execute(OWNER_UPSERT, catalog.owners)

        owner_ids = dict(session.execute(text(
            "SELECT source_owner_id, id FROM water_authority_station_owners"
        )).all())
        station_rows = [
            {
                **station,
                "cell_id": cell_for(station["latitude"], station["longitude"]),
                "owner_id": owner_ids[station["owner_source_id"]],
            }
            for station in catalog.stations
        ]
        session.execute(STATION_UPSERT, station_rows)

        station_ids = dict(session.execute(text(
            "SELECT source_station_id, id FROM hydrometric_stations"
        )).all())
        session.execute(text("DELETE FROM hydrometric_station_rain_links"))
        link_rows = [
            {
                **link,
                "hydrometric_station_id": station_ids[
                    link["hydrometric_station_source_id"]
                ],
            }
            for link in catalog.rain_links
        ]
        if link_rows:
            session.execute(LINK_INSERT, link_rows)

        session.execute(
            text(
                """
                INSERT INTO static_layer_imports
                  (layer_name, source_url, source_version, content_sha256,
                   feature_count, checked_at, loaded_at)
                VALUES
                  ('hydrometric_stations', :source_url, :source_version,
                   :content_sha256, :feature_count, :checked_at, :loaded_at)
                ON CONFLICT (layer_name) DO UPDATE SET
                  source_url = EXCLUDED.source_url,
                  source_version = EXCLUDED.source_version,
                  content_sha256 = EXCLUDED.content_sha256,
                  feature_count = EXCLUDED.feature_count,
                  checked_at = EXCLUDED.checked_at,
                  loaded_at = EXCLUDED.loaded_at
                """
            ),
            {
                "source_url": catalog.source_url,
                "source_version": catalog.source_version,
                "content_sha256": catalog.checksum,
                "feature_count": len(catalog.stations),
                "checked_at": checked_at,
                "loaded_at": checked_at,
            },
        )
        session.commit()

    return {
        "owners": len(catalog.owners),
        "stations": len(catalog.stations),
        "rain_links": len(catalog.rain_links),
    }


def load_hydrometric_station_catalog(
    http_session: requests.Session | None = None,
) -> dict[str, int]:
    """Fetch, persist and account for one station-catalog synchronization."""
    from ecoguard.database.repositories.collector_runs import log_finish, log_start

    run_id = log_start(SOURCE)
    try:
        result = persist_hydrometric_station_catalog(
            fetch_hydrometric_station_catalog(http_session)
        )
        log_finish(run_id, status="ok", rows_written=sum(result.values()))
        return result
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise
