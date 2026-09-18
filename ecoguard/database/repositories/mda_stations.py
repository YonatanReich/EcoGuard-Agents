"""Reading the Magen David Adom station reference table.

Written by scripts/load_mda_stations.py from MDA's own roster, positioned from
the OpenStreetMap export where that covers a station and from the published
address otherwise. `precision` says which, because they are not comparable: a
building is the station, a street is the road it is on, and a city is the town
centroid.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session


def mda_stations_geojson() -> dict[str, Any]:
    """Every MDA station that has coordinates, as GeoJSON points.

    Stations whose roster entry gives no address, or an address no gazetteer
    resolves, are absent from features but still counted — a map cannot draw a
    station without a position, and `total` is what stops it implying MDA has
    fewer stations than it does.
    """
    with Session() as session:
        rows = session.execute(text("""
            SELECT id,
                   station_id,
                   name,
                   locality,
                   address,
                   ST_Y(location::geometry) AS latitude,
                   ST_X(location::geometry) AS longitude,
                   source->>'precision' AS precision,
                   coalesce(source->>'source', 'nominatim') AS position_source
            FROM mda_stations
            WHERE location IS NOT NULL
            ORDER BY name
        """)).mappings().all()

        total = session.execute(text("SELECT count(*) FROM mda_stations")).scalar_one()

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
                "locality": row["locality"],
                "address": row["address"],
                "precision": row["precision"],
                "source": row["position_source"],
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
