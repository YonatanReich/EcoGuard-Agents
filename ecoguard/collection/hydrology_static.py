"""Download and persist the Water Authority's static map layers.

This is deliberately a one-shot loader rather than a scheduled collector. The
files are reference data, so an operator or another system component invokes it
when the database is first prepared and whenever a source version changes.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Callable

import requests
from sqlalchemy import text


DEFAULT_BASE_URL = "https://hydro.water.gov.il"
BASE_URL = os.getenv("WATER_AUTHORITY_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
REQUEST_TIMEOUT_SECONDS = 60
CHUNK_SIZE = 500
SOURCE = "water_authority_static"
REQUEST_HEADERS = {
    # The public host rejects a bare requests/EcoGuard user agent. Keep the
    # client honestly identified while using the Mozilla-compatible form
    # accepted by the same host for map assets.
    "User-Agent": "Mozilla/5.0 (compatible; EcoGuard-Agents/1.0)",
    "Accept": "application/geo+json,application/json",
    "Referer": f"{BASE_URL}/index.php/?page=hydro_obs&lang=he",
}


class StaticHydrologyLayerError(ValueError):
    """The provider returned a document that cannot safely be persisted."""


@dataclass(frozen=True)
class LayerSpec:
    name: str
    path: str
    table: str
    allowed_geometry_types: frozenset[str]
    row_builder: Callable[[dict[str, Any], datetime], dict[str, Any]]

    @property
    def url(self) -> str:
        return f"{BASE_URL}{self.path}"


@dataclass(frozen=True)
class DownloadedLayer:
    spec: LayerSpec
    source_url: str
    source_version: str
    checksum: str
    rows: list[dict[str, Any]]


def _required_int(properties: dict[str, Any], name: str, layer: str) -> int:
    value = properties.get(name)
    if value is None or isinstance(value, bool):
        raise StaticHydrologyLayerError(f"{layer} feature is missing integer property {name}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise StaticHydrologyLayerError(
            f"{layer} feature has invalid integer property {name}: {value!r}"
        ) from error


def _optional_int(properties: dict[str, Any], name: str) -> int | None:
    value = properties.get(name)
    return None if value is None else int(value)


def _optional_text(properties: dict[str, Any], name: str) -> str | None:
    value = properties.get(name)
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _properties(feature: dict[str, Any], layer: str) -> dict[str, Any]:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise StaticHydrologyLayerError(f"{layer} feature has no properties object")
    return properties


def _serialized_geometry(feature: dict[str, Any], layer: str) -> str:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise StaticHydrologyLayerError(f"{layer} feature has no geometry object")
    return json.dumps(geometry, ensure_ascii=False, separators=(",", ":"))


def _serialized_properties(properties: dict[str, Any]) -> str:
    return json.dumps(properties, ensure_ascii=False, separators=(",", ":"))


def _basin_row(feature: dict[str, Any], imported_at: datetime) -> dict[str, Any]:
    properties = _properties(feature, "drainage_basins")
    return {
        "basin_id": _required_int(properties, "basin_id", "drainage_basins"),
        "area_id": _optional_int(properties, "area_id"),
        "name_he": _optional_text(properties, "b_n_heb"),
        "name_en": _optional_text(properties, "b_n_eng"),
        "area_code": _optional_int(properties, "area_c"),
        "geometry": _serialized_geometry(feature, "drainage_basins"),
        "properties": _serialized_properties(properties),
        "imported_at": imported_at,
    }


def _stream_row(feature: dict[str, Any], imported_at: datetime) -> dict[str, Any]:
    properties = _properties(feature, "streams")
    return {
        "object_id": _required_int(properties, "OBJECTID", "streams"),
        "name_he": _optional_text(properties, "STREAM_NAME_H") or _optional_text(properties, "NAME"),
        "water_source_id": _optional_int(properties, "WATER_SOURCE_ID"),
        "main_catchment_code": _optional_text(properties, "MAIN_CATCH_CD"),
        "main_catchment_name": _optional_text(properties, "MAIN_CAT_1"),
        "draining_water_id": _optional_int(properties, "DRAINING_WATER_ID"),
        "draining_water_name": _optional_text(properties, "DRAIN_WATER_NAME"),
        "geometry": _serialized_geometry(feature, "streams"),
        "properties": _serialized_properties(properties),
        "imported_at": imported_at,
    }


def _road_marker_row(feature: dict[str, Any], imported_at: datetime) -> dict[str, Any]:
    properties = _properties(feature, "road_km_markers")
    road_number = _optional_text(properties, "ROADNUM")
    kilometer = properties.get("KM")
    if road_number is None or kilometer is None:
        raise StaticHydrologyLayerError(
            "road_km_markers feature is missing ROADNUM or KM"
        )
    return {
        "object_id": _required_int(properties, "OBJECTID", "road_km_markers"),
        "road_number": road_number,
        "kilometer": float(kilometer),
        "israel_grid_x": properties.get("X"),
        "israel_grid_y": properties.get("Y"),
        "road_type": _optional_text(properties, "TYPE_ROAD"),
        "geometry": _serialized_geometry(feature, "road_km_markers"),
        "properties": _serialized_properties(properties),
        "imported_at": imported_at,
    }


LAYERS = (
    LayerSpec(
        name="drainage_basins",
        path="/data/geojson/basins_v12.1.geojson",
        table="drainage_basins",
        allowed_geometry_types=frozenset({"Polygon", "MultiPolygon"}),
        row_builder=_basin_row,
    ),
    LayerSpec(
        name="streams",
        path="/data/geojson/streams_v1.geojson",
        table="streams",
        allowed_geometry_types=frozenset({"LineString", "MultiLineString"}),
        row_builder=_stream_row,
    ),
    LayerSpec(
        name="road_km_markers",
        path="/data/geojson/road_km.geojson",
        table="road_km_markers",
        allowed_geometry_types=frozenset({"Point"}),
        row_builder=_road_marker_row,
    ),
)


INSERT_STATEMENTS = {
    "drainage_basins": text(
        """
        INSERT INTO drainage_basins
          (basin_id, area_id, name_he, name_en, area_code, geometry, properties, imported_at)
        VALUES (
          :basin_id, :area_id, :name_he, :name_en, :area_code,
          ST_Multi(ST_CollectionExtract(ST_MakeValid(
            ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)
          ), 3))::geometry(MultiPolygon, 4326),
          CAST(:properties AS jsonb), :imported_at
        )
        """
    ),
    "streams": text(
        """
        INSERT INTO streams
          (object_id, name_he, water_source_id, main_catchment_code,
           main_catchment_name, draining_water_id, draining_water_name,
           geometry, properties, imported_at)
        VALUES (
          :object_id, :name_he, :water_source_id, :main_catchment_code,
          :main_catchment_name, :draining_water_id, :draining_water_name,
          ST_Multi(ST_CollectionExtract(
            ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326), 2
          ))::geometry(MultiLineString, 4326),
          CAST(:properties AS jsonb), :imported_at
        )
        """
    ),
    "road_km_markers": text(
        """
        INSERT INTO road_km_markers
          (object_id, road_number, kilometer, israel_grid_x, israel_grid_y,
           road_type, location, properties, imported_at)
        VALUES (
          :object_id, :road_number, :kilometer, :israel_grid_x, :israel_grid_y,
          :road_type,
          ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)::geography,
          CAST(:properties AS jsonb), :imported_at
        )
        """
    ),
}


def _canonical_checksum(document: dict[str, Any]) -> str:
    canonical = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def parse_layer(
    spec: LayerSpec,
    content: bytes,
    *,
    imported_at: datetime | None = None,
) -> DownloadedLayer:
    """Validate one FeatureCollection and turn it into database-ready rows."""
    try:
        document = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StaticHydrologyLayerError(f"{spec.name} is not valid UTF-8 GeoJSON") from error

    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise StaticHydrologyLayerError(f"{spec.name} is not a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise StaticHydrologyLayerError(f"{spec.name} contains no features")

    imported_at = imported_at or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    identities: set[int] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise StaticHydrologyLayerError(f"{spec.name} feature {index} is invalid")
        geometry = feature.get("geometry")
        geometry_type = geometry.get("type") if isinstance(geometry, dict) else None
        if geometry_type not in spec.allowed_geometry_types:
            raise StaticHydrologyLayerError(
                f"{spec.name} feature {index} has unsupported geometry {geometry_type!r}"
            )
        row = spec.row_builder(feature, imported_at)
        identity = row.get("basin_id", row.get("object_id"))
        if identity in identities:
            raise StaticHydrologyLayerError(
                f"{spec.name} contains duplicate source identity {identity}"
            )
        identities.add(identity)
        rows.append(row)

    source_version = str(document.get("name") or PurePosixPath(spec.path).name)
    return DownloadedLayer(
        spec=spec,
        source_url=spec.url,
        source_version=source_version,
        checksum=_canonical_checksum(document),
        rows=rows,
    )


def download_layers(
    http_session: requests.Session | None = None,
) -> list[DownloadedLayer]:
    """Download and fully validate all layers before opening a DB transaction."""
    http = http_session or requests.Session()
    imported_at = datetime.now(timezone.utc)
    downloaded = []
    for spec in LAYERS:
        response = http.get(
            spec.url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        downloaded.append(parse_layer(spec, response.content, imported_at=imported_at))
    return downloaded


def _chunks(rows: list[dict[str, Any]]):
    for start in range(0, len(rows), CHUNK_SIZE):
        yield rows[start:start + CHUNK_SIZE]


def persist_layers(layers: list[DownloadedLayer]) -> dict[str, int]:
    """Atomically replace changed layers and return rows written per layer."""
    # Keep the database import at the persistence boundary. Download/validation
    # can then be used by diagnostics and tests without requiring DATABASE_URL.
    from ecoguard.database.engine import Session

    result: dict[str, int] = {}
    checked_at = datetime.now(timezone.utc)
    with Session() as session:
        for layer in layers:
            existing_checksum = session.execute(
                text(
                    "SELECT content_sha256 FROM static_layer_imports "
                    "WHERE layer_name = :layer_name"
                ),
                {"layer_name": layer.spec.name},
            ).scalar_one_or_none()

            if existing_checksum == layer.checksum:
                session.execute(
                    text(
                        "UPDATE static_layer_imports SET checked_at = :checked_at "
                        "WHERE layer_name = :layer_name"
                    ),
                    {"checked_at": checked_at, "layer_name": layer.spec.name},
                )
                result[layer.spec.name] = 0
                continue

            # table comes only from the hard-coded LAYERS tuple, never from the
            # network response or command line.
            session.execute(text(f"DELETE FROM {layer.spec.table}"))
            statement = INSERT_STATEMENTS[layer.spec.name]
            for chunk in _chunks(layer.rows):
                session.execute(statement, chunk)

            session.execute(
                text(
                    """
                    INSERT INTO static_layer_imports
                      (layer_name, source_url, source_version, content_sha256,
                       feature_count, checked_at, loaded_at)
                    VALUES
                      (:layer_name, :source_url, :source_version, :content_sha256,
                       :feature_count, :checked_at, :loaded_at)
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
                    "layer_name": layer.spec.name,
                    "source_url": layer.source_url,
                    "source_version": layer.source_version,
                    "content_sha256": layer.checksum,
                    "feature_count": len(layer.rows),
                    "checked_at": checked_at,
                    "loaded_at": checked_at,
                },
            )
            result[layer.spec.name] = len(layer.rows)
        session.commit()
    return result


def load_static_hydrology_layers(
    http_session: requests.Session | None = None,
) -> dict[str, int]:
    """Download all three layers, persist changes, and account for the run."""
    from ecoguard.database.repositories.collector_runs import log_finish, log_start

    run_id = log_start(SOURCE)
    try:
        result = persist_layers(download_layers(http_session))
        log_finish(run_id, status="ok", rows_written=sum(result.values()))
        return result
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise
