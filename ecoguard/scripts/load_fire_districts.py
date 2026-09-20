"""Load the seven fire district polygons, so a footprint can be placed in one.

    python -m ecoguard.scripts.load_fire_districts

Dispatch is territorial before it is proximate: each district handles events in
its own sector, and a neighbouring district assists only by exception. That rule
cannot be applied without knowing which district the fire is in, and until now
the polygons existed only as a committed GeoJSON file that nothing read.

A full reload. District boundaries are reference data published once, not a
feed, and a half-replaced set of polygons would place fires in the wrong
sector without failing.

Note the name spelling: this file says `יו"ש`, matching `towns.fire_district`,
while `fire_stations.district` says `יהודה ושומרון`. That mismatch already cost
122 towns their responsible stations once; `responsible_services` owns the
alias and everything here goes through it.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.paths import REFERENCE

SOURCE = REFERENCE / "fire_districts.geojson"

DDL = """
CREATE TABLE IF NOT EXISTS fire_districts (
  district   text PRIMARY KEY,
  areas      text[],
  boundary   geography(MultiPolygon, 4326) NOT NULL,
  loaded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fire_districts_boundary
  ON fire_districts USING gist (boundary);
"""


def load() -> int:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = []
    for feature in payload.get("features", ()):
        properties = feature.get("properties") or {}
        district = properties.get("district")
        geometry = feature.get("geometry")
        if not district or not geometry:
            continue
        # Forced to MultiPolygon so the column type is uniform whether a
        # district arrived as one polygon or several.
        rows.append({
            "district": district,
            "areas": properties.get("areas") or [],
            "geojson": json.dumps(geometry),
        })

    with Session() as session:
        for statement in DDL.split(";"):
            if statement.strip():
                session.execute(text(statement))
        session.commit()

        session.execute(text("TRUNCATE fire_districts"))
        session.execute(
            text(
                """
                INSERT INTO fire_districts (district, areas, boundary)
                VALUES (
                  :district, :areas,
                  ST_Multi(ST_MakeValid(
                    ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326)
                  ))::geography
                )
                """
            ),
            rows,
        )
        session.commit()
    return len(rows)


def main() -> None:
    count = load()
    with Session() as session:
        summary = session.execute(
            text(
                """
                SELECT district,
                       round((ST_Area(boundary) / 1e6)::numeric) AS km2,
                       array_length(areas, 1) AS areas
                FROM fire_districts ORDER BY km2 DESC
                """
            )
        ).all()
        stations = session.execute(
            text(
                """
                SELECT d.district, count(f.id)
                FROM fire_districts d
                LEFT JOIN fire_stations f
                  ON f.district = CASE d.district
                                    WHEN 'יו"ש' THEN 'יהודה ושומרון'
                                    ELSE d.district END
                 AND f.location IS NOT NULL
                GROUP BY d.district ORDER BY d.district
                """
            )
        ).all()

    print(f"{count} districts loaded")
    for district, km2, areas in summary:
        print(f"  {district:10} {km2:>7,} km2   {areas} areas")
    print("\nlocated stations per district:")
    for district, count in stations:
        flag = "  <-- none" if not count else ""
        print(f"  {district:10} {count}{flag}")


if __name__ == "__main__":
    main()
