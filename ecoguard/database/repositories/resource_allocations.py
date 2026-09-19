"""Transactional persistence for emergency-station allocations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import text

from ecoguard.database.engine import Session


STATION_COLUMNS = {
    "fire_department": "fire_station_id",
    "police": "police_station_id",
    "medical_services": "mda_station_id",
}


class ResourceAllocationRepository:
    """Store active claims and their release history in PostgreSQL."""

    @staticmethod
    def _station_column(recommended_unit: str) -> str:
        try:
            return STATION_COLUMNS[recommended_unit]
        except KeyError as error:
            raise ValueError(
                f"unsupported allocation resource: {recommended_unit}"
            ) from error

    def claim_stations(
        self,
        *,
        incident_id: str,
        recommended_unit: str,
        candidates: Iterable[dict[str, Any]],
        required_count: int,
        risk_score: float,
        risk_level: str,
        allocated_at: datetime,
    ) -> list[dict[str, Any]]:
        """Assign stations without exceeding one incident's demand.

        Fire and MDA stations are exclusive while active. Police stations may
        receive several incidents because the allocation represents area
        responsibility, not a particular vehicle.
        """
        station_column = self._station_column(recommended_unit)

        with Session() as session:
            with session.begin():
                # Serializing on the incident prevents concurrent retries from
                # allocating more stations than this incident requested.
                incident_exists = session.execute(
                    text("SELECT id FROM incidents WHERE id = :id FOR UPDATE"),
                    {"id": incident_id},
                ).scalar_one_or_none()
                if incident_exists is None:
                    raise ValueError(f"incident does not exist: {incident_id}")

                rows = session.execute(
                    text(
                        f"""
                        SELECT id,
                               incident_id,
                               '{recommended_unit}' AS recommended_unit,
                               {station_column} AS station_id,
                               allocated_at,
                               released_at,
                               release_reason,
                               distance_km,
                               risk_score,
                               risk_level
                        FROM resource_allocations
                        WHERE incident_id = :incident_id
                          AND released_at IS NULL
                          AND {station_column} IS NOT NULL
                        ORDER BY allocated_at, id
                        """
                    ),
                    {"incident_id": incident_id},
                ).mappings().all()
                active = [dict(row) for row in rows]
                active_station_ids = {
                    row["station_id"] for row in active
                }

                for candidate in candidates:
                    if len(active) >= required_count:
                        break

                    station_id = candidate["database_id"]
                    if station_id in active_station_ids:
                        continue

                    inserted = session.execute(
                        text(
                            f"""
                            INSERT INTO resource_allocations (
                              incident_id,
                              {station_column},
                              allocated_at,
                              distance_km,
                              risk_score,
                              risk_level
                            ) VALUES (
                              :incident_id,
                              :station_id,
                              :allocated_at,
                              :distance_km,
                              :risk_score,
                              :risk_level
                            )
                            ON CONFLICT DO NOTHING
                            RETURNING id,
                                      incident_id,
                                      '{recommended_unit}' AS recommended_unit,
                                      {station_column} AS station_id,
                                      allocated_at,
                                      released_at,
                                      release_reason,
                                      distance_km,
                                      risk_score,
                                      risk_level
                            """
                        ),
                        {
                            "incident_id": incident_id,
                            "station_id": station_id,
                            "allocated_at": allocated_at,
                            "distance_km": candidate["distance_km"],
                            "risk_score": risk_score,
                            "risk_level": risk_level,
                        },
                    ).mappings().first()
                    if inserted is None:
                        # A concurrent retry already created the claim, or an
                        # exclusive fire/MDA station was claimed first.
                        continue

                    row = dict(inserted)
                    active.append(row)
                    active_station_ids.add(station_id)

        return active

    def release_incident(
        self,
        incident_id: str,
        *,
        released_at: datetime,
        reason: str,
    ) -> list[dict[str, Any]]:
        """Release all active stations for an incident, idempotently."""
        with Session() as session:
            with session.begin():
                incident_exists = session.execute(
                    text("SELECT id FROM incidents WHERE id = :id FOR UPDATE"),
                    {"id": incident_id},
                ).scalar_one_or_none()
                if incident_exists is None:
                    raise ValueError(f"incident does not exist: {incident_id}")

                rows = session.execute(
                    text(
                        """
                        UPDATE resource_allocations
                        SET released_at = :released_at,
                            release_reason = :reason
                        WHERE incident_id = :incident_id
                          AND released_at IS NULL
                        RETURNING id,
                                  incident_id,
                                  CASE
                                    WHEN fire_station_id IS NOT NULL
                                      THEN 'fire_department'
                                    WHEN police_station_id IS NOT NULL
                                      THEN 'police'
                                    ELSE 'medical_services'
                                  END AS recommended_unit,
                                  coalesce(
                                    fire_station_id,
                                    police_station_id,
                                    mda_station_id
                                  ) AS station_id,
                                  allocated_at,
                                  released_at,
                                  release_reason,
                                  distance_km,
                                  risk_score,
                                  risk_level
                        """
                    ),
                    {
                        "incident_id": incident_id,
                        "released_at": released_at,
                        "reason": reason,
                    },
                ).mappings().all()

        return [dict(row) for row in rows]

    def active_allocations(self) -> list[dict[str, Any]]:
        """Return every currently active station claim."""
        with Session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT id,
                           incident_id,
                           CASE
                             WHEN fire_station_id IS NOT NULL
                               THEN 'fire_department'
                             WHEN police_station_id IS NOT NULL
                               THEN 'police'
                             ELSE 'medical_services'
                           END AS recommended_unit,
                           coalesce(
                             fire_station_id,
                             police_station_id,
                             mda_station_id
                           ) AS station_id,
                           allocated_at,
                           released_at,
                           release_reason,
                           distance_km,
                           risk_score,
                           risk_level
                    FROM resource_allocations
                    WHERE released_at IS NULL
                    ORDER BY incident_id, allocated_at, id
                    """
                )
            ).mappings().all()

        return [dict(row) for row in rows]
