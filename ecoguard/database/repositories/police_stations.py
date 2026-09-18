"""Reading the police station reference table.

Written by scripts/load_police_stations.py from the Israel Police published
list. Unlike the fire stations there is no precision to report: every row is an
exact published coordinate, so the API carries no basis field for the map to
qualify a dot with.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session


def police_stations_geojson() -> dict[str, Any]:
    """Every police station as a GeoJSON point.

    `located` and `total` are always equal — location is NOT NULL on this table
    — but both are returned so the shape matches /api/fire-stations and the
    frontend control can render either the same way.
    """
    with Session() as session:
        rows = session.execute(text("""
            SELECT id,
                   station_id,
                   name,
                   kind,
                   city,
                   address,
                   phone,
                   ST_Y(location::geometry) AS latitude,
                   ST_X(location::geometry) AS longitude
            FROM police_stations
            ORDER BY kind, name
        """)).mappings().all()

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["longitude"], row["latitude"]],
            },
            "properties": {
                "database_id": row["id"],
                "station_id": row["station_id"],
                "name": row["name"],
                # district | region | station | post | base | centre — the rank
                # of the site, which is what says whether this is a
                # headquarters or a two-officer post.
                "kind": row["kind"],
                "city": row["city"],
                "address": row["address"],
                "phone": row["phone"],
            },
        }
        for row in rows
    ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "located": len(features),
        "total": len(features),
    }
