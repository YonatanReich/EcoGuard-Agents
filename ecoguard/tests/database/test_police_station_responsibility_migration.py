"""Schema and seed contracts for town-to-police responsibility."""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT
    / "ecoguard"
    / "database"
    / "migrations"
    / "versions"
    / "0022_police_station_responsibility.py"
)
REFERENCE = ROOT / "ecoguard" / "data" / "reference"
CROSSWALK = REFERENCE / "Town info" / "police_station_crosswalk.csv"


def test_migration_adds_normalized_town_police_responsibility():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "police_station_responsibility"' in source
    assert 'down_revision = "flood_incident_lifecycle"' in source
    assert "CREATE TABLE town_police_stations" in source
    assert "REFERENCES towns(town_id)" in source
    assert "REFERENCES police_stations(id)" in source


def test_police_allocation_is_shared_across_incidents_but_idempotent():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "DROP INDEX IF EXISTS resource_allocations_active_police_idx" in source
    assert "resource_allocations_active_incident_police_idx" in source
    assert "(incident_id, police_station_id)" in source


def test_crosswalk_covers_every_towns_station_name_and_uses_seed_ids():
    towns = json.loads((REFERENCE / "towns.json").read_text(encoding="utf-8"))
    seed = json.loads(
        (REFERENCE / "stations_seed.json").read_text(encoding="utf-8")
    )
    with CROSSWALK.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    expected_names = {
        name.strip()
        for town in towns
        for name in (town.get("police_station") or "").split(",")
        if name.strip()
    }
    seed_ids = {
        str(station["station_id"])
        for station in seed["police_stations"]
    }

    assert len(rows) == 88
    assert {row["towns_station_name"] for row in rows} == expected_names
    assert sum(bool(row["police_station_id"]) for row in rows) == 85
    assert {
        row["police_station_id"]
        for row in rows
        if row["police_station_id"]
    } <= seed_ids
