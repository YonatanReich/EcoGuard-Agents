"""Import a routable road-line GeoJSON layer for flood spatial screening.

The flood allocator needs complete line geometry; Mapbox Directions only
answers routing questions after a destination is already known.  This module
therefore accepts a local GeoJSON export (normally OpenStreetMap-derived),
normalises its road taxonomy to Mapbox Streets classes, and replaces one
source's rows atomically in ``road_segments``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import text

from ecoguard.database.engine import Session


ROAD_CLASSES = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "street",
        "street_limited",
        "service",
        "track",
        "pedestrian",
        "path",
    }
)

OSM_HIGHWAY_TO_CLASS = {
    "motorway": "motorway",
    "motorway_link": "motorway_link",
    "trunk": "trunk",
    "trunk_link": "trunk_link",
    "primary": "primary",
    "primary_link": "primary_link",
    "secondary": "secondary",
    "secondary_link": "secondary_link",
    "tertiary": "tertiary",
    "tertiary_link": "tertiary_link",
    "residential": "street",
    "unclassified": "street",
    "road": "street",
    "living_street": "street",
    "service": "service",
    "track": "track",
    "pedestrian": "pedestrian",
    "footway": "path",
    "path": "path",
    "steps": "path",
    "cycleway": "path",
    "bridleway": "path",
}

_FALSE_VALUES = {"no", "false", "0"}
_TRUE_VALUES = {"yes", "true", "1", "designated", "permissive"}


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _structure_flag(value: object) -> bool:
    """OSM bridge/tunnel values may be types such as viaduct or culvert."""

    normalized = str(value or "").strip().lower()
    return bool(normalized) and normalized not in _FALSE_VALUES


def normalize_road_class(properties: Mapping[str, Any]) -> str | None:
    """Return the Mapbox-compatible class of one road feature."""

    declared = _text(properties.get("class") or properties.get("road_class"))
    if declared in ROAD_CLASSES:
        return declared
    return OSM_HIGHWAY_TO_CLASS.get(
        str(properties.get("highway") or "").strip().lower()
    )


def vehicle_access(properties: Mapping[str, Any]) -> bool | None:
    """Interpret whether any motor vehicle may use the segment.

    Emergency-specific permission wins.  ``None`` means that the source did
    not state an access rule; it is deliberately different from a prohibition.
    """

    emergency = str(properties.get("emergency") or "").strip().lower()
    if emergency in _TRUE_VALUES:
        return True
    for key in ("motor_vehicle", "vehicle", "access"):
        raw = properties.get(key)
        if raw is None:
            continue
        value = str(raw).strip().lower()
        if value in _FALSE_VALUES or value == "private":
            return False
        if value in _TRUE_VALUES or value == "destination":
            return True
    return None


def _feature_identity(feature: Mapping[str, Any], properties: Mapping[str, Any]) -> str:
    explicit = (
        feature.get("id")
        or properties.get("osm_id")
        or properties.get("OBJECTID")
        or properties.get("object_id")
        or properties.get("id")
    )
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    stable = json.dumps(
        {
            "geometry": feature.get("geometry"),
            "properties": dict(properties),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def road_records(
    features: Iterable[Mapping[str, Any]],
    *,
    source: str,
    imported_at: datetime,
) -> list[dict[str, Any]]:
    """Validate and normalise GeoJSON road features into database rows."""

    rows: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, Mapping) or geometry.get("type") not in {
            "LineString",
            "MultiLineString",
        }:
            continue
        properties = feature.get("properties") or {}
        if not isinstance(properties, Mapping):
            continue
        road_class = normalize_road_class(properties)
        if road_class is None:
            continue
        rows.append(
            {
                "source": source,
                "source_feature_id": _feature_identity(feature, properties),
                "road_class": road_class,
                "name": _text(
                    properties.get("name:he")
                    or properties.get("name_he")
                    or properties.get("name")
                ),
                "road_ref": _text(properties.get("ref") or properties.get("road_ref")),
                "bridge": _structure_flag(properties.get("bridge")),
                "tunnel": _structure_flag(properties.get("tunnel")),
                "vehicle_access": vehicle_access(properties),
                "geometry": json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
                "properties": json.dumps(
                    dict(properties), ensure_ascii=False, sort_keys=True
                ),
                "imported_at": imported_at,
            }
        )
    return rows


def replace_road_source(
    path: str | Path,
    *,
    source: str = "openstreetmap",
    session_factory=Session,
) -> int:
    """Atomically replace one source's local road geometry from GeoJSON."""

    source_name = str(source).strip()
    if not source_name:
        raise ValueError("road source is required")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("road input must be a GeoJSON FeatureCollection")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("road input has no features array")

    rows = road_records(
        features,
        source=source_name,
        imported_at=datetime.now(timezone.utc),
    )
    if not rows:
        raise ValueError("road input contains no supported road lines")

    insert = text(
        """
        INSERT INTO road_segments (
          source, source_feature_id, road_class, name, road_ref,
          bridge, tunnel, vehicle_access, geometry, properties, imported_at
        ) VALUES (
          :source, :source_feature_id, :road_class, :name, :road_ref,
          :bridge, :tunnel, :vehicle_access,
          ST_Multi(ST_CollectionExtract(
            ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326), 2
          ))::geometry(MultiLineString, 4326),
          CAST(:properties AS jsonb), :imported_at
        )
        """
    )
    with session_factory() as session:
        with session.begin():
            session.execute(
                text("DELETE FROM road_segments WHERE source = :source"),
                {"source": source_name},
            )
            session.execute(insert, rows)
    return len(rows)


__all__ = [
    "ROAD_CLASSES",
    "normalize_road_class",
    "replace_road_source",
    "road_records",
    "vehicle_access",
]
