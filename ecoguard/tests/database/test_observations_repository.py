"""Idempotent writes and a real PostGIS round-trip. Needs a migrated database."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ecoguard.database.repositories.observations import upsert_observations

SOURCE = "test_source"


def _cleanup(engine):
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM observations WHERE source = :source"), {"source": SOURCE}
        )


def test_the_same_reading_written_twice_produces_one_row(database):
    _cleanup(database)
    record = {
        "cell_id": "risk-05000m-r0010-c0010",
        "latitude": 31.5,
        "longitude": 35.0,
        "observed_at": datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
        "payload": {"hotspot_count": 1},
    }

    assert upsert_observations(SOURCE, [record]) == 1
    assert upsert_observations(SOURCE, [record]) == 0

    with database.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM observations WHERE source = :s"), {"s": SOURCE}
        ).scalar()
    assert count == 1
    _cleanup(database)


def test_a_different_hour_of_the_same_cell_is_a_new_row(database):
    _cleanup(database)
    base = {
        "cell_id": "risk-05000m-r0010-c0010",
        "latitude": 31.5,
        "longitude": 35.0,
        "payload": {},
    }
    hour = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)

    written = upsert_observations(SOURCE, [
        {**base, "observed_at": hour},
        {**base, "observed_at": hour + timedelta(hours=1)},
    ])

    assert written == 2
    _cleanup(database)


def test_a_point_survives_the_round_trip(database):
    _cleanup(database)
    upsert_observations(SOURCE, [{
        "cell_id": "postgis-round-trip",
        "latitude": 32.0853,
        "longitude": 34.7818,
        "observed_at": datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
        "payload": {},
    }])

    with database.connect() as connection:
        latitude, longitude = connection.execute(text(
            "SELECT ST_Y(location::geometry), ST_X(location::geometry) "
            "FROM observations WHERE cell_id = 'postgis-round-trip'"
        )).one()

    assert round(latitude, 4) == 32.0853
    assert round(longitude, 4) == 34.7818
    _cleanup(database)


def test_a_source_without_coordinates_stores_a_null_location(database):
    _cleanup(database)
    upsert_observations(SOURCE, [{
        "cell_id": "mdaisrael:12345",
        "observed_at": datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
        "payload": {"text": "raw hebrew message"},
    }])

    with database.connect() as connection:
        location = connection.execute(text(
            "SELECT location FROM observations WHERE cell_id = 'mdaisrael:12345'"
        )).scalar()

    assert location is None
    _cleanup(database)
