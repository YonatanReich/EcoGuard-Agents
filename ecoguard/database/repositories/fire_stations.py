"""Reading the fire station reference table.

Written by scripts/seed_fire_stations.py, not by a collector: this is a
published list that changes when the authority republishes it, not a time
series. There is no observed_at to pick a latest row by.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session


def fire_stations_geojson() -> dict[str, Any]:
    """Every station that has coordinates, as GeoJSON points.

    Stations whose published address could not be resolved to a point are left
    out of features — a map cannot draw a station without a location — but they
    are still counted, so the caller can say how much of the list is on screen
    rather than implying the country has ten fewer stations than it does.
    """
    with Session() as session:
        rows = session.execute(text("""
            SELECT district,
                   name,
                   regional,
                   address,
                   ST_Y(location::geometry) AS latitude,
                   ST_X(location::geometry) AS longitude,
                   geocode->>'precision' AS precision,
                   coalesce(geocode->>'source', 'nominatim') AS source,
                   tags
            FROM fire_stations
            WHERE location IS NOT NULL
            ORDER BY district, name
        """)).mappings().all()

        total = session.execute(text("SELECT count(*) FROM fire_stations")).scalar_one()

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["longitude"], row["latitude"]],
            },
            "properties": {
                "name": row["name"],
                "district": row["district"],
                "regional": row["regional"],
                "address": row["address"],
                # building (the mapped station itself), street, neighborhood or
                # city. A city-precision station sits on the town centroid, not
                # the station, and anything reasoning about dispatch distance
                # needs to know which of the four it is looking at.
                "precision": row["precision"],
                # "osm" means the point is the station building; "nominatim"
                # means it was derived from the published postal address.
                "source": row["source"],
                # Only a handful of stations carry these, so they are emitted
                # only when present rather than as a wall of nulls.
                **{
                    key: (row["tags"] or {})[tag]
                    for key, tag in (
                        ("phone", "phone"),
                        ("website", "website"),
                        ("opening_hours", "opening_hours"),
                        ("operator", "operator"),
                    )
                    if (row["tags"] or {}).get(tag)
                },
            },
        }
        for row in rows
    ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "located": len(features),
        "total": total,
    }
