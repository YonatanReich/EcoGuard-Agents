"""Seed the three emergency service station tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-10
"""

import json
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# The station tables hold static reference data: the fire, police and MDA
# station rosters, positioned once against OpenStreetMap and the published
# addresses. That work does not need repeating, so the finished rows ship here
# rather than in loader scripts that would have to re-geocode a few hundred
# addresses against a rate-limited public service to rebuild what is already
# known.
#
# Kept beside the migration as JSON rather than inlined: 133 KB of Hebrew data
# embedded in a Python file is unreadable and unreviewable in a diff.
SEED_PATH = Path("data/reference/stations_seed.json")

INSERTS = {
    "fire_stations": """
        INSERT INTO fire_stations
          (district, name, regional, address, location, geocode, tags)
        VALUES (
          :district, :name, :regional, :address,
          ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                  CAST(:lat AS double precision)), 4326)::geography,
          CAST(:geocode AS jsonb), CAST(:tags AS jsonb)
        )
        ON CONFLICT ON CONSTRAINT fire_stations_identity DO NOTHING
    """,
    "police_stations": """
        INSERT INTO police_stations
          (station_id, name, kind, city, address, phone, location, source)
        VALUES (
          :station_id, :name, :kind, :city, :address, :phone,
          ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                  CAST(:lat AS double precision)), 4326)::geography,
          CAST(:source AS jsonb)
        )
        ON CONFLICT ON CONSTRAINT police_stations_identity DO NOTHING
    """,
    "mda_stations": """
        INSERT INTO mda_stations
          (station_id, name, locality, address, location, source)
        VALUES (
          :station_id, :name, :locality, :address,
          ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                  CAST(:lat AS double precision)), 4326)::geography,
          CAST(:source AS jsonb)
        )
        ON CONFLICT ON CONSTRAINT mda_stations_identity DO NOTHING
    """,
}

# Columns holding JSON. psycopg will not adapt a dict into a jsonb bind on its
# own, so they are serialised before binding.
JSON_COLUMNS = ("geocode", "tags", "source")


def upgrade() -> None:
    if not SEED_PATH.exists():
        # Nothing to seed is not a failure: an operator running migrations from
        # somewhere without the data file still gets the schema.
        return

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    connection = op.get_bind()

    for table, statement in INSERTS.items():
        rows = seed.get(table) or []
        for row in rows:
            connection.execute(text(statement), {
                key: (json.dumps(value, ensure_ascii=False)
                      if key in JSON_COLUMNS else value)
                for key, value in row.items()
            })


def downgrade() -> None:
    # Only the seeded rows go. A station added later by hand is not this
    # migration's to remove, but the tables are dropped by 0002/0004/0005
    # anyway, so a full downgrade loses nothing extra.
    pass
