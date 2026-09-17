"""Load a national locality GeoJSON into the shared PostGIS reference table.

This script performs no download. It accepts an explicit local FeatureCollection,
validates its identifiers and geometry envelopes, and writes all rows in one
transaction. Use ``--replace`` for a deterministic full-cohort replacement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import engine


@dataclass(frozen=True)
class LocalityImportRow:
    locality_code: str
    name_he: str
    name_en: str | None
    locality_type: str | None
    source_resource_id: str | None
    geometry_json: str
    raw_properties_json: str


def _nonblank(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def parse_feature_collection(
    payload: dict[str, Any],
    *,
    code_field: str,
    name_he_field: str,
    name_en_field: str,
    type_field: str,
    resource_id_field: str,
) -> list[LocalityImportRow]:
    """Validate source structure before beginning a database transaction."""

    if payload.get("type") != "FeatureCollection":
        raise ValueError("input_must_be_geojson_feature_collection")
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("feature_collection_is_empty")
    rows = []
    seen: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"invalid_feature:{index}")
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            raise ValueError(f"missing_properties_or_geometry:{index}")
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"non_polygon_geometry:{index}")
        code = _nonblank(properties.get(code_field))
        name_he = _nonblank(properties.get(name_he_field))
        if code is None or name_he is None:
            raise ValueError(f"missing_locality_identity:{index}")
        if code in seen:
            raise ValueError(f"duplicate_locality_code:{code}")
        seen.add(code)
        rows.append(
            LocalityImportRow(
                locality_code=code,
                name_he=name_he,
                name_en=_nonblank(properties.get(name_en_field)),
                locality_type=_nonblank(properties.get(type_field)),
                source_resource_id=_nonblank(properties.get(resource_id_field)),
                geometry_json=json.dumps(geometry, ensure_ascii=False),
                raw_properties_json=json.dumps(properties, ensure_ascii=False),
            )
        )
    return sorted(rows, key=lambda row: row.locality_code)


_INSERT_SQL = text(
    """
    WITH source_geometry AS (
      SELECT ST_Transform(
               ST_SetSRID(ST_GeomFromGeoJSON(:geometry_json), :source_srid),
               4326
             ) AS geom
    ), normalized AS (
      SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3)) AS boundary
      FROM source_geometry
    )
    INSERT INTO localities (
      locality_code, name_he, name_en, locality_type, boundary,
      representative_point, source, source_resource_id, source_updated_at,
      imported_at, source_version, source_checksum, raw_properties
    )
    SELECT
      :locality_code, :name_he, :name_en, :locality_type, boundary,
      ST_PointOnSurface(boundary), :source, :source_resource_id,
      :source_updated_at, now(), :source_version, :source_checksum,
      CAST(:raw_properties_json AS jsonb)
    FROM normalized
    WHERE NOT ST_IsEmpty(boundary) AND ST_IsValid(boundary)
    ON CONFLICT (locality_code) DO UPDATE SET
      name_he = EXCLUDED.name_he,
      name_en = EXCLUDED.name_en,
      locality_type = EXCLUDED.locality_type,
      boundary = EXCLUDED.boundary,
      representative_point = EXCLUDED.representative_point,
      source = EXCLUDED.source,
      source_resource_id = EXCLUDED.source_resource_id,
      source_updated_at = EXCLUDED.source_updated_at,
      imported_at = EXCLUDED.imported_at,
      source_version = EXCLUDED.source_version,
      source_checksum = EXCLUDED.source_checksum,
      raw_properties = EXCLUDED.raw_properties
    RETURNING locality_code
    """
)


def load_localities(
    path: Path,
    *,
    source: str,
    source_version: str | None,
    source_updated_at: datetime | None,
    source_srid: int,
    code_field: str,
    name_he_field: str,
    name_en_field: str,
    type_field: str,
    resource_id_field: str,
    replace: bool,
) -> int:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8-sig"))
    rows = parse_feature_collection(
        payload,
        code_field=code_field,
        name_he_field=name_he_field,
        name_en_field=name_en_field,
        type_field=type_field,
        resource_id_field=resource_id_field,
    )
    checksum = hashlib.sha256(raw).hexdigest()
    with engine.begin() as connection:
        if connection.execute(
            text("SELECT to_regclass('public.localities')")
        ).scalar_one() is None:
            raise RuntimeError("localities_table_missing_run_migrations_first")
        if replace:
            connection.execute(text("DELETE FROM localities"))
        written = 0
        for row in rows:
            result = connection.execute(
                _INSERT_SQL,
                {
                    **row.__dict__,
                    "source": source,
                    "source_updated_at": source_updated_at,
                    "source_version": source_version,
                    "source_checksum": checksum,
                    "source_srid": source_srid,
                },
            ).scalar_one_or_none()
            if result is None:
                raise ValueError(f"invalid_geometry:{row.locality_code}")
            written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-version")
    parser.add_argument("--source-updated-at", type=datetime.fromisoformat)
    parser.add_argument("--source-srid", type=int, default=4326)
    parser.add_argument("--code-field", default="locality_code")
    parser.add_argument("--name-he-field", default="name_he")
    parser.add_argument("--name-en-field", default="name_en")
    parser.add_argument("--type-field", default="locality_type")
    parser.add_argument("--resource-id-field", default="source_resource_id")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    count = load_localities(**vars(args))
    print(f"Imported {count} localities into shared PostGIS.")


if __name__ == "__main__":
    main()
