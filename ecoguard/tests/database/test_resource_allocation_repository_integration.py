"""PostgreSQL integration coverage for atomic station allocation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from ecoguard.database.repositories.resource_allocations import (
    ResourceAllocationRepository,
)


def _insert_incident(connection, incident_id):
    now = datetime.now(timezone.utc)
    connection.execute(
        text(
            """
            INSERT INTO incidents (
              id, status, primary_hazard, hazards, queues, cells,
              latitude, longitude, precision_m, location_method,
              first_seen_at, last_signal_at, signal_count
            ) VALUES (
              :id, 'open', 'flood', ARRAY['flood'], ARRAY['emergency'],
              ARRAY['integration-test'], 31.778, 35.223, 10,
              'integration_test', :now, :now, 1
            )
            """
        ),
        {"id": incident_id, "now": now},
    )


def _candidate(database_id):
    return {
        "database_id": database_id,
        "distance_km": 1.0,
    }


def _claim(repository, incident_id, unit, station_id):
    return repository.claim_stations(
        incident_id=incident_id,
        recommended_unit=unit,
        candidates=[_candidate(station_id)],
        required_count=1,
        risk_score=50.0,
        risk_level="moderate",
        allocated_at=datetime.now(timezone.utc),
    )


def test_police_station_can_cover_two_incidents_and_release_one(database):
    suffix = uuid4().hex
    incident_ids = [f"integration-police-a-{suffix}", f"integration-police-b-{suffix}"]
    published_station_id = int(suffix[:15], 16)

    with database.begin() as connection:
        station_id = connection.execute(
            text(
                """
                INSERT INTO police_stations (
                  station_id, name, kind, city, location, source
                ) VALUES (
                  :published_id, :name, 'station', 'integration-test',
                  ST_SetSRID(ST_MakePoint(35.223, 31.778), 4326)::geography,
                  '{}'::jsonb
                )
                RETURNING id
                """
            ),
            {
                "published_id": published_station_id,
                "name": f"integration-police-{suffix}",
            },
        ).scalar_one()
        for incident_id in incident_ids:
            _insert_incident(connection, incident_id)

    repository = ResourceAllocationRepository()
    try:
        first = _claim(repository, incident_ids[0], "police", station_id)
        second = _claim(repository, incident_ids[1], "police", station_id)

        assert len(first) == 1
        assert len(second) == 1

        released = repository.release_incident(
            incident_ids[0],
            released_at=datetime.now(timezone.utc),
            reason="integration_test",
        )
        assert len(released) == 1

        active_for_second = [
            allocation
            for allocation in repository.active_allocations()
            if allocation["incident_id"] == incident_ids[1]
        ]
        assert len(active_for_second) == 1

        reassigned = _claim(repository, incident_ids[0], "police", station_id)
        assert len(reassigned) == 1
    finally:
        with database.begin() as connection:
            connection.execute(
                text("DELETE FROM resource_allocations WHERE incident_id = ANY(:ids)"),
                {"ids": incident_ids},
            )
            connection.execute(
                text("DELETE FROM incidents WHERE id = ANY(:ids)"),
                {"ids": incident_ids},
            )
            connection.execute(
                text("DELETE FROM police_stations WHERE id = :id"),
                {"id": station_id},
            )


def test_concurrent_fire_claims_are_exclusive_in_postgres(database):
    suffix = uuid4().hex
    incident_ids = [f"integration-fire-a-{suffix}", f"integration-fire-b-{suffix}"]

    with database.begin() as connection:
        station_id = connection.execute(
            text(
                """
                INSERT INTO fire_stations (
                  district, name, regional, location, geocode
                ) VALUES (
                  'integration-test', :name, false,
                  ST_SetSRID(ST_MakePoint(35.223, 31.778), 4326)::geography,
                  '{}'::jsonb
                )
                RETURNING id
                """
            ),
            {"name": f"integration-fire-{suffix}"},
        ).scalar_one()
        for incident_id in incident_ids:
            _insert_incident(connection, incident_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda incident_id: _claim(
                        ResourceAllocationRepository(),
                        incident_id,
                        "fire_department",
                        station_id,
                    ),
                    incident_ids,
                )
            )

        assert sorted(len(result) for result in results) == [0, 1]
    finally:
        with database.begin() as connection:
            connection.execute(
                text("DELETE FROM resource_allocations WHERE incident_id = ANY(:ids)"),
                {"ids": incident_ids},
            )
            connection.execute(
                text("DELETE FROM incidents WHERE id = ANY(:ids)"),
                {"ids": incident_ids},
            )
            connection.execute(
                text("DELETE FROM fire_stations WHERE id = :id"),
                {"id": station_id},
            )
