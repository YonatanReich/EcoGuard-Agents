"""towns — one row per settlement, with its outline and who answers for it

Revision ID: towns
Revises: firms_baselines
Create Date: 2026-09-17

Non-numeric identifier for the same reason as the ones before it: sibling
branches claim numeric ids and alembic resolves stored revisions by prefix.
"""

import json

from alembic import op
from sqlalchemy import text

from ecoguard.paths import REFERENCE

revision = "towns"
down_revision = "firms_baselines"
branch_labels = None
depends_on = None

SEED_PATH = REFERENCE / "towns.json"


def upgrade() -> None:
    # The settlement level, which nothing in this schema had before. The
    # station tables know where the responders are and `incidents` knows where
    # the fire is; this is the missing third thing — where the people are.
    #
    # Why a table rather than the GeoJSON the frontend already loads: the
    # spread analyser has to ask "which towns does this forecast ring cross",
    # and that is a spatial join over 2,000 polygons on every evaluation. In
    # the file it is a full scan in Python; here it is a GiST index.
    #
    # `outline` is geography rather than geometry to match the station tables,
    # so distances come back in metres without anyone choosing a projection.
    # The trade is that a few operators need a ::geometry cast, which the
    # repository does explicitly.
    #
    # MultiPolygon rather than Polygon because a town is not always one piece:
    # Ariel is its built-up area plus a detached industrial estate two
    # kilometres west, and storing only the larger part would leave a fire in
    # that estate intersecting nothing.
    #
    # Contact details are denormalised onto the town rather than living in an
    # authorities table. 59% of rows have a phone and the number belongs to the
    # authority, not the town — but an operator reading this row wants the
    # number in it, and a join table of 250 authorities to save 1,200 repeated
    # strings is bookkeeping that buys nothing at this size.
    #
    # `*_match` records how each name-joined field was resolved — exact, prefix,
    # fuzzy or miss. The two source lists disagree about Hebrew spelling and
    # some joins are approximate; recording which ones lets a wrong police
    # station be found later rather than silently trusted.
    # IF NOT EXISTS, and a seed that yields to existing rows, because this
    # table was applied to the shared database out-of-band: alembic there is
    # stamped on a revision from the flood branch and cannot run, and stamping
    # it forward would have stranded that branch. A reference table with no
    # foreign keys, whose contents come from a file, is the one kind of
    # migration where making it re-runnable costs nothing and saves a manual
    # reconciliation later. A fresh database still gets the table and all rows.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS towns (
          town_id           text    PRIMARY KEY,
          name_he           text    NOT NULL,
          name_en           text    NOT NULL,
          place             text,
          population        integer,
          households        integer,
          cbs_code          text,

          -- How the outline was obtained: 'place' (someone drew this
          -- settlement in OSM), 'built-up clipped', 'built-up', or
          -- 'municipal boundary'. The last overstates a town by whatever open
          -- land its municipality holds, and a reader comparing burnt area to
          -- town area needs to know which kind it has.
          outline_source    text,

          fire_district     text,
          authority         text,
          authority_type    text,
          authority_phone   text,
          authority_address text,
          authority_website text,
          authority_match   text,

          police_station    text,
          police_region     text,
          police_district   text,
          police_match      text,

          area_km2          double precision,

          -- Where a popup should open. The polygon's representative point, not
          -- its centroid: a centroid can fall outside a concave outline.
          label_lat         double precision NOT NULL,
          label_lon         double precision NOT NULL,

          -- Precomputed so a search result can frame the map without the
          -- client fetching and measuring the polygon first.
          min_lon           double precision NOT NULL,
          min_lat           double precision NOT NULL,
          max_lon           double precision NOT NULL,
          max_lat           double precision NOT NULL,

          outline           geography(MultiPolygon, 4326) NOT NULL
        )
        """
    )

    # The spatial index the analyser's ring-versus-town join rides on.
    op.execute("CREATE INDEX IF NOT EXISTS towns_outline_gix ON towns USING GIST (outline)")

    # Prefix search as the operator types. text_pattern_ops is what lets a
    # btree serve LIKE 'foo%' — the default collation-aware opclass cannot.
    op.execute("CREATE INDEX IF NOT EXISTS towns_name_he_prefix ON towns (name_he text_pattern_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS towns_name_en_prefix ON towns (lower(name_en) text_pattern_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS towns_fire_district ON towns (fire_district)")

    connection = op.get_bind()
    existing = connection.execute(text("SELECT count(*) FROM towns")).scalar()
    if existing:
        print(f"towns: {existing} rows already present, leaving them alone")
        return

    if not SEED_PATH.exists():
        # The table is still correct without its contents; scripts/build_towns.py
        # regenerates the seed. Failing the migration would make a fresh
        # checkout unable to reach head.
        print(f"towns: {SEED_PATH} missing, table created empty")
        return

    towns = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    statement = text(
        """
        INSERT INTO towns (
          town_id, name_he, name_en, place, population, households,
          cbs_code, outline_source,
          fire_district, authority, authority_type, authority_phone,
          authority_address, authority_website, authority_match,
          police_station, police_region, police_district, police_match,
          area_km2, label_lat, label_lon,
          min_lon, min_lat, max_lon, max_lat, outline
        ) VALUES (
          :town_id, :name_he, :name_en, :place, :population, :households,
          :cbs_code, :outline_source,
          :fire_district, :authority, :authority_type, :authority_phone,
          :authority_address, :authority_website, :authority_match,
          :police_station, :police_region, :police_district, :police_match,
          :area_km2, :label_lat, :label_lon,
          :min_lon, :min_lat, :max_lon, :max_lat,
          ST_GeogFromText(:outline_wkt)
        )
        """
    )

    rows = []
    for town in towns:
        geometry = town["geometry"]
        # Outer rings only, and every part. Holes are dropped on purpose, to
        # match what exposure.load_localities reads from the file: a hole in a
        # town outline is a park or a quarry, and a fire there is still a fire
        # in the town.
        parts = ([geometry["coordinates"]] if geometry["type"] == "Polygon"
                 else geometry["coordinates"])
        outline_wkt = "MULTIPOLYGON({})".format(",".join(
            "(({}))".format(",".join(f"{x} {y}" for x, y in part[0]))
            for part in parts
        ))
        bbox = town["bbox"]
        rows.append({
            "town_id": town["town_id"],
            "name_he": town["name_he"],
            "name_en": town["name_en"],
            "place": town["place"],
            "population": town["population"],
            "households": town["households"],
            "cbs_code": town["cbs_code"],
            "outline_source": town["outline_source"],
            "fire_district": town["fire_district"],
            "authority": town["authority"],
            "authority_type": town["authority_type"],
            "authority_phone": town["authority_phone"],
            "authority_address": town["authority_address"],
            "authority_website": town["authority_website"],
            "authority_match": town["authority_match"],
            "police_station": town["police_station"],
            "police_region": town["police_region"],
            "police_district": town["police_district"],
            "police_match": town["police_match"],
            "area_km2": town["area_km2"],
            "label_lat": town["label_lat"],
            "label_lon": town["label_lon"],
            "min_lon": bbox[0], "min_lat": bbox[1],
            "max_lon": bbox[2], "max_lat": bbox[3],
            "outline_wkt": outline_wkt,
        })

    connection.execute(statement, rows)
    print(f"towns: loaded {len(rows)} settlements")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS towns")
