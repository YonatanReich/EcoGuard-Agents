"""Cache the official historical station registry and map it to live stations.

The hydrograph CSV files use the Water Authority's long-lived station number,
while the live endpoint uses a different numeric key.  This module keeps both
identities separate and materializes their spatial/name match once.  Runtime
collectors and the detector never perform this work.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping

import requests
from rasterio.warp import transform
from sqlalchemy import text


SOURCE = "water_authority_historical_station_registry"
LAYER_NAME = "historical_hydrometric_stations"
RESOURCE_ID = "a0522b41-00ad-4367-a00a-2d97b050ec1d"
DATASTORE_URL = "https://data.gov.il/api/3/action/datastore_search"
REQUEST_TIMEOUT_SECONDS = 60
PAGE_SIZE = 1000
MAX_AUTOMATIC_DISTANCE_M = 500.0
EXACT_COORDINATE_DISTANCE_M = 100.0
MIN_NAME_SIMILARITY = 0.72


class HistoricalStationRegistryError(ValueError):
    """The public station registry cannot be safely cached or matched."""


@dataclass(frozen=True)
class HistoricalStationCatalog:
    source_url: str
    source_version: str
    checksum: str
    rows: list[dict[str, Any]]


def _required_int(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    if value is None or isinstance(value, bool):
        raise HistoricalStationRegistryError(f"station row is missing {field}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise HistoricalStationRegistryError(
            f"station row has invalid {field}: {value!r}"
        ) from error


def _optional_int(row: Mapping[str, Any], field: str) -> int | None:
    value = row.get(field)
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise HistoricalStationRegistryError(
            f"station row has invalid {field}: {value!r}"
        )
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise HistoricalStationRegistryError(
            f"station row has invalid {field}: {value!r}"
        ) from error


def _optional_float(row: Mapping[str, Any], field: str) -> float | None:
    value = row.get(field)
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise HistoricalStationRegistryError(
            f"station row has invalid {field}: {value!r}"
        )
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise HistoricalStationRegistryError(
            f"station row has invalid {field}: {value!r}"
        ) from error


def _optional_text(row: Mapping[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _optional_date(row: Mapping[str, Any], field: str) -> date | None:
    value = _optional_text(row, field)
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError as error:
        raise HistoricalStationRegistryError(
            f"station row has invalid {field}: {value!r}"
        ) from error


def _optional_yes_no(row: Mapping[str, Any], field: str) -> bool | None:
    value = _optional_text(row, field)
    if value is None:
        return None
    if value == "כן":
        return True
    if value == "לא":
        return False
    raise HistoricalStationRegistryError(
        f"station row has invalid {field}: {value!r}"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def parse_historical_station_catalog(
    records: Iterable[Mapping[str, Any]],
    *,
    synced_at: datetime | None = None,
) -> HistoricalStationCatalog:
    """Validate DataStore records and convert ITM coordinates to WGS84."""
    source_rows = [dict(record) for record in records]
    if not source_rows:
        raise HistoricalStationRegistryError("station registry contains no records")

    parsed: list[dict[str, Any]] = []
    identities: set[int] = set()
    coordinate_rows: list[int] = []
    xs: list[float] = []
    ys: list[float] = []
    synced_at = synced_at or datetime.now(timezone.utc)

    for source_row in source_rows:
        station_id = _required_int(source_row, "זיהוי תחנה")
        if station_id in identities:
            raise HistoricalStationRegistryError(
                f"station registry repeats identity {station_id}"
            )
        identities.add(station_id)
        name_he = _optional_text(source_row, "שם עברית")
        name_en = _optional_text(source_row, "שם אנגלית")
        if name_he is None and name_en is None:
            raise HistoricalStationRegistryError(
                f"historical station {station_id} has no name"
            )
        x = _optional_float(source_row, "נ.צ. X (רוחב)")
        y = _optional_float(source_row, "נ.צ. Y (רוחב)")
        if (x is None) != (y is None):
            raise HistoricalStationRegistryError(
                f"historical station {station_id} has incomplete coordinates"
            )
        parsed.append(
            {
                "source_station_id": station_id,
                "name_he": name_he,
                "name_en": name_en,
                "established_on": _optional_date(source_row, "תאריך הקמה"),
                "catchment_area_km2": _optional_float(
                    source_row, "שטח היקוות (קמ''ר)"
                ),
                "shared_catchment": _optional_yes_no(source_row, "שטח משותף"),
                "israel_grid_x": x,
                "israel_grid_y": y,
                "group_source_station_id": _optional_int(
                    source_row, "מספר קבוצה"
                ),
                "main_drainage_name": _optional_text(
                    source_row, "תחום התנקזות של נחל ראשי"
                ),
                "current_status": _optional_text(
                    source_row, "סטטוס תחנה נוכחי"
                ),
                "source_metadata": _canonical_json(source_row),
                "synced_at": synced_at,
                "is_in_current_registry": True,
                "latitude": None,
                "longitude": None,
            }
        )
        if x is not None and y is not None:
            coordinate_rows.append(len(parsed) - 1)
            xs.append(x)
            ys.append(y)

    if coordinate_rows:
        try:
            longitudes, latitudes = transform("EPSG:2039", "EPSG:4326", xs, ys)
        except Exception as error:
            raise HistoricalStationRegistryError(
                "station registry coordinates cannot be transformed from EPSG:2039"
            ) from error
    else:
        longitudes, latitudes = [], []
    for row_index, longitude, latitude in zip(
        coordinate_rows, longitudes, latitudes
    ):
        row = parsed[row_index]
        if not (28.0 <= latitude <= 34.5 and 33.0 <= longitude <= 36.5):
            raise HistoricalStationRegistryError(
                f"historical station {row['source_station_id']} is outside Israel"
            )
        row["latitude"] = float(latitude)
        row["longitude"] = float(longitude)

    checksum_rows = sorted(source_rows, key=lambda row: int(row["זיהוי תחנה"]))
    checksum = hashlib.sha256(_canonical_json(checksum_rows).encode("utf-8")).hexdigest()
    return HistoricalStationCatalog(
        source_url=f"{DATASTORE_URL}?resource_id={RESOURCE_ID}",
        source_version=RESOURCE_ID,
        checksum=checksum,
        rows=parsed,
    )


def fetch_historical_station_catalog(
    http_session: requests.Session | None = None,
) -> HistoricalStationCatalog:
    """Read every current row through the public CKAN DataStore API."""
    http = http_session or requests.Session()
    records: list[dict[str, Any]] = []
    total: int | None = None
    offset = 0
    while total is None or offset < total:
        response = http.get(
            DATASTORE_URL,
            params={
                "resource_id": RESOURCE_ID,
                "limit": PAGE_SIZE,
                "offset": offset,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        page = result.get("records") if isinstance(result, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("success") is not True
            or not isinstance(page, list)
        ):
            raise HistoricalStationRegistryError(
                "station registry API returned an invalid DataStore response"
            )
        if total is None:
            try:
                total = int(result["total"])
            except (KeyError, TypeError, ValueError) as error:
                raise HistoricalStationRegistryError(
                    "station registry API did not provide a valid total"
                ) from error
        if not page and offset < total:
            raise HistoricalStationRegistryError(
                "station registry API ended before the declared total"
            )
        records.extend(page)
        offset += len(page)
    if total != len(records):
        raise HistoricalStationRegistryError(
            f"station registry declared {total} rows but returned {len(records)}"
        )
    return parse_historical_station_catalog(records)


def _normalized_name(value: Any) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value)).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _name_similarity(
    historical: Mapping[str, Any], current: Mapping[str, Any]
) -> float:
    scores = []
    for field in ("name_en", "name_he"):
        left = _normalized_name(historical.get(field))
        right = _normalized_name(current.get(field))
        if left and right:
            scores.append(SequenceMatcher(None, left, right).ratio())
    return max(scores, default=0.0)


def _distance_m(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    latitude_1 = math.radians(float(left["latitude"]))
    latitude_2 = math.radians(float(right["latitude"]))
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = math.radians(
        float(right["longitude"]) - float(left["longitude"])
    )
    haversine = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_1)
        * math.cos(latitude_2)
        * math.sin(delta_longitude / 2) ** 2
    )
    return 6_371_008.8 * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def automatic_station_links(
    historical_stations: Iterable[Mapping[str, Any]],
    current_stations: Iterable[Mapping[str, Any]],
    *,
    matched_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return conservative links; distant and weak candidates stay unmatched."""
    current = list(current_stations)
    matched_at = matched_at or datetime.now(timezone.utc)
    links: list[dict[str, Any]] = []
    for historical in historical_stations:
        if (
            historical.get("latitude") is None
            or historical.get("longitude") is None
        ):
            continue
        candidates: list[tuple[float, float, float, str, Mapping[str, Any]]] = []
        for station in current:
            if station.get("latitude") is None or station.get("longitude") is None:
                continue
            distance = _distance_m(historical, station)
            if distance > MAX_AUTOMATIC_DISTANCE_M:
                continue
            similarity = _name_similarity(historical, station)
            if distance <= EXACT_COORDINATE_DISTANCE_M:
                method = "automatic_coordinates"
                confidence = 0.94 + 0.04 * similarity - 0.02 * (
                    distance / EXACT_COORDINATE_DISTANCE_M
                )
            elif similarity >= MIN_NAME_SIMILARITY:
                method = "automatic_coordinates_name"
                confidence = (
                    0.68
                    + 0.20 * similarity
                    + 0.08 * (1.0 - distance / MAX_AUTOMATIC_DISTANCE_M)
                )
            else:
                continue
            candidates.append(
                (confidence, similarity, -distance, method, station)
            )
        if not candidates:
            continue
        confidence, similarity, negative_distance, method, station = max(
            candidates, key=lambda candidate: candidate[:3]
        )
        distance = -negative_distance
        links.append(
            {
                "historical_station_id": int(historical["source_station_id"]),
                "hydrometric_station_id": int(station["id"]),
                "match_method": method,
                "distance_m": round(distance, 3),
                "name_similarity": round(similarity, 6),
                "confidence": round(min(confidence, 0.99), 6),
                "reviewed": False,
                "matched_at": matched_at,
            }
        )
    return links


UPSERT_HISTORICAL_STATION = text(
    """
    INSERT INTO historical_hydrometric_stations (
      source_station_id, name_he, name_en, established_on,
      catchment_area_km2, shared_catchment, israel_grid_x, israel_grid_y,
      group_source_station_id, main_drainage_name, current_status, location,
      source_metadata, synced_at, is_in_current_registry
    ) VALUES (
      :source_station_id, :name_he, :name_en, :established_on,
      :catchment_area_km2, :shared_catchment, :israel_grid_x, :israel_grid_y,
      :group_source_station_id, :main_drainage_name, :current_status,
      CASE
        WHEN CAST(:longitude AS double precision) IS NULL
          OR CAST(:latitude AS double precision) IS NULL THEN NULL
        ELSE ST_SetSRID(
          ST_MakePoint(
            CAST(:longitude AS double precision),
            CAST(:latitude AS double precision)
          ),
          4326
        )::geography
      END,
      CAST(:source_metadata AS jsonb), :synced_at, :is_in_current_registry
    )
    ON CONFLICT (source_station_id) DO UPDATE SET
      name_he = EXCLUDED.name_he,
      name_en = EXCLUDED.name_en,
      established_on = EXCLUDED.established_on,
      catchment_area_km2 = EXCLUDED.catchment_area_km2,
      shared_catchment = EXCLUDED.shared_catchment,
      israel_grid_x = EXCLUDED.israel_grid_x,
      israel_grid_y = EXCLUDED.israel_grid_y,
      group_source_station_id = EXCLUDED.group_source_station_id,
      main_drainage_name = EXCLUDED.main_drainage_name,
      current_status = EXCLUDED.current_status,
      location = EXCLUDED.location,
      source_metadata = EXCLUDED.source_metadata,
      synced_at = EXCLUDED.synced_at,
      is_in_current_registry = true
    """
)


INSERT_LINK = text(
    """
    INSERT INTO hydrometric_station_history_links (
      historical_station_id, hydrometric_station_id, match_method,
      distance_m, name_similarity, confidence, reviewed, matched_at
    ) VALUES (
      :historical_station_id, :hydrometric_station_id, :match_method,
      :distance_m, :name_similarity, :confidence, :reviewed, :matched_at
    )
    ON CONFLICT (historical_station_id) DO NOTHING
    """
)


def persist_historical_station_catalog(
    catalog: HistoricalStationCatalog,
) -> int:
    """Upsert the source cache without overwriting reviewed station links."""
    from ecoguard.database.engine import Session

    checked_at = datetime.now(timezone.utc)
    with Session() as session:
        existing_checksum = session.execute(
            text(
                "SELECT content_sha256 FROM static_layer_imports "
                "WHERE layer_name = :layer_name"
            ),
            {"layer_name": LAYER_NAME},
        ).scalar_one_or_none()
        if existing_checksum == catalog.checksum:
            session.execute(
                text(
                    "UPDATE static_layer_imports SET checked_at = :checked_at "
                    "WHERE layer_name = :layer_name"
                ),
                {"checked_at": checked_at, "layer_name": LAYER_NAME},
            )
            session.commit()
            return 0

        session.execute(
            text(
                "UPDATE historical_hydrometric_stations "
                "SET is_in_current_registry = false"
            )
        )
        session.execute(UPSERT_HISTORICAL_STATION, catalog.rows)
        session.execute(
            text(
                """
                INSERT INTO static_layer_imports (
                  layer_name, source_url, source_version, content_sha256,
                  feature_count, checked_at, loaded_at
                ) VALUES (
                  :layer_name, :source_url, :source_version, :content_sha256,
                  :feature_count, :checked_at, :loaded_at
                )
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
                "layer_name": LAYER_NAME,
                "source_url": catalog.source_url,
                "source_version": catalog.source_version,
                "content_sha256": catalog.checksum,
                "feature_count": len(catalog.rows),
                "checked_at": checked_at,
                "loaded_at": checked_at,
            },
        )
        session.commit()
    return len(catalog.rows)


def refresh_historical_station_links() -> int:
    """Recompute only unreviewed links after either station catalog changes."""
    from ecoguard.database.engine import Session

    with Session() as session:
        reviewed_ids = set(
            session.execute(
                text(
                    "SELECT historical_station_id "
                    "FROM hydrometric_station_history_links WHERE reviewed"
                )
            ).scalars()
        )
        historical = [
            dict(row)
            for row in session.execute(
                text(
                    """
                    SELECT source_station_id, name_he, name_en,
                           ST_Y(location::geometry) AS latitude,
                           ST_X(location::geometry) AS longitude
                    FROM historical_hydrometric_stations
                    WHERE is_in_current_registry
                      AND location IS NOT NULL
                    ORDER BY source_station_id
                    """
                )
            ).mappings()
            if row["source_station_id"] not in reviewed_ids
        ]
        current = [
            dict(row)
            for row in session.execute(
                text(
                    """
                    SELECT id, source_station_id, name_he, name_en,
                           ST_Y(location::geometry) AS latitude,
                           ST_X(location::geometry) AS longitude
                    FROM hydrometric_stations
                    WHERE is_active
                      AND flow_threshold_status = 'complete_thresholds'
                    ORDER BY source_station_id
                    """
                )
            ).mappings()
        ]
        links = automatic_station_links(historical, current)
        session.execute(
            text("DELETE FROM hydrometric_station_history_links WHERE NOT reviewed")
        )
        if links:
            session.execute(INSERT_LINK, links)
        session.commit()
    return len(links)


def load_historical_station_registry(
    http_session: requests.Session | None = None,
) -> dict[str, int]:
    """Cache the public registry and refresh its links to live stations."""
    from ecoguard.database.repositories.collector_runs import log_finish, log_start

    run_id = log_start(SOURCE)
    try:
        catalog = fetch_historical_station_catalog(http_session)
        result = {
            "historical_stations": persist_historical_station_catalog(catalog),
            "automatic_links": refresh_historical_station_links(),
        }
        log_finish(run_id, status="ok", rows_written=sum(result.values()))
        return result
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise
