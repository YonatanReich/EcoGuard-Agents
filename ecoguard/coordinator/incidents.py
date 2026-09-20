"""Reading and writing incidents — the only stateful thing the coordinator owns.

Raw SQL and a session per call, like every other repository here. Returns plain
dicts rather than rows, so the rest of the coordinator never imports SQLAlchemy.

One deliberate shape: signals live in a jsonb array on the incident rather than
in a child table. The array is bounded because the incident closes after its
quiet period; every read this table gets is incident-level (`status`, `cells`,
`last_signal_at`) and never reaches inside the array; and the read-modify-write
that appending would otherwise race on is already serialised by the
`single_flight` lock around the whole run. A child table would buy a cheaper
append and cost a join on the common path.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.database.repositories.resource_allocations import (
    release_incident_allocations_in_session,
)
from ecoguard.shared.signals import CellSignal

OPEN = "open"
CLOSED = "closed"

_COLUMNS = """
    id, status, primary_hazard, hazards, queues, cells,
    latitude, longitude, precision_m, location_method,
    first_seen_at, last_signal_at, closed_at,
    signal_count, peak_rarity, links, signals
"""


def signal_as_json(signal: CellSignal) -> dict[str, Any]:
    """A signal flattened for storage, keeping everything that explains it.

    Stored rather than summarised because an incident has to be able to show
    its working: which source said what, when, and how unusual it was. A
    merged incident whose evidence has been averaged away cannot be argued
    with, only believed.
    """
    record = asdict(signal)
    record["observed_at"] = signal.observed_at.isoformat()
    return record


def _row(row) -> dict[str, Any]:
    incident = dict(row)
    # jsonb comes back parsed; text[] comes back as a list. Normalise the
    # array columns to lists so callers never see a tuple from one driver and
    # a list from another.
    for column in ("hazards", "queues", "cells"):
        incident[column] = list(incident[column] or [])
    return incident


def next_incident_id(at: datetime) -> str:
    """A readable, sortable id: INC-20260914-0003.

    Readable because a human reads it aloud to another human during an
    incident. Date-prefixed so the sequence resets daily and stays short, and
    so an id says roughly when without a lookup.
    """
    day = at.astimezone(timezone.utc).strftime("%Y%m%d")
    with Session() as session:
        used = session.execute(
            text("SELECT count(*) FROM incidents WHERE id LIKE :prefix"),
            {"prefix": f"INC-{day}-%"},
        ).scalar_one()
    return f"INC-{day}-{used + 1:04d}"


def open_incidents(hazards: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Every open incident, newest signal first.

    Optionally narrowed to incidents touching any of `hazards`, which is what
    the matcher wants — a fire signal never needs to consider flood incidents.
    """
    query = f"SELECT {_COLUMNS} FROM incidents WHERE status = :open"
    params: dict[str, Any] = {"open": OPEN}
    if hazards is not None:
        query += " AND hazards && :hazards"
        params["hazards"] = list(hazards)
    query += " ORDER BY last_signal_at DESC"

    with Session() as session:
        return [_row(row) for row in session.execute(text(query), params).mappings()]


def incident_by_id(incident_id: str) -> dict[str, Any] | None:
    with Session() as session:
        row = session.execute(
            text(f"SELECT {_COLUMNS} FROM incidents WHERE id = :id"),
            {"id": incident_id},
        ).mappings().first()
    return _row(row) if row else None


def create_incident(
    incident_id: str,
    signal: CellSignal,
    queues: Iterable[str],
) -> dict[str, Any]:
    """Open a new incident from the first signal that did not match anything."""
    location = signal.location
    with Session() as session:
        session.execute(
            text(
                """
                INSERT INTO incidents (
                  id, status, primary_hazard, hazards, queues, cells,
                  latitude, longitude, precision_m, location_method,
                  first_seen_at, last_signal_at,
                  signal_count, peak_rarity, links, signals
                ) VALUES (
                  :id, :status, :hazard, :hazards, :queues, :cells,
                  :latitude, :longitude, :precision_m, :location_method,
                  :at, :at,
                  1, :rarity, '[]'::jsonb, CAST(:signals AS jsonb)
                )
                """
            ),
            {
                "id": incident_id,
                "status": OPEN,
                "hazard": signal.hazard,
                "hazards": [signal.hazard],
                "queues": list(queues),
                "cells": [signal.cell_id],
                "latitude": location.latitude if location else None,
                "longitude": location.longitude if location else None,
                "precision_m": location.precision_m if location else None,
                "location_method": location.method if location else None,
                "at": signal.observed_at,
                "rarity": signal.rarity,
                "signals": json.dumps([signal_as_json(signal)]),
            },
        )
        session.commit()
    return incident_by_id(incident_id)


def attach_signal(incident_id: str, signal: CellSignal) -> dict[str, Any] | None:
    """Fold another sighting into an incident that already exists.

    The location only improves: a better fix replaces a worse one and a worse
    one is ignored, never averaged. Averaging a 375 m satellite pixel with a
    2 km town-name geocode produces a place neither source suggested and throws
    away the good fix.

    `last_signal_at` only advances, so a late-arriving old reading — routine
    with FIRMS, which runs hours behind the overpass — cannot drag an incident
    backwards and make it look quiet.
    """
    location = signal.location
    current = incident_by_id(incident_id)
    if current is None:
        return None

    # Whether this fix beats the one already stored. Decided in Python rather
    # than in SQL because the comparison involves two nullable values and the
    # three-valued logic reads as a puzzle inside a CASE expression.
    stored_precision = current["precision_m"]
    better = location is not None and (
        stored_precision is None or location.precision_m < stored_precision
    )

    with Session() as session:
        session.execute(
            text(
                """
                UPDATE incidents SET
                  cells = CASE WHEN :cell = ANY(cells) THEN cells
                               ELSE array_append(cells, :cell) END,
                  last_signal_at = GREATEST(last_signal_at, :at),
                  signal_count = signal_count + 1,
                  peak_rarity = GREATEST(coalesce(peak_rarity, 0), coalesce(:rarity, 0)),
                  signals = signals || CAST(:signal AS jsonb),
                  latitude = CASE WHEN :better THEN CAST(:latitude AS double precision)
                                  ELSE latitude END,
                  longitude = CASE WHEN :better THEN CAST(:longitude AS double precision)
                                   ELSE longitude END,
                  location_method = CASE WHEN :better THEN CAST(:location_method AS text)
                                         ELSE location_method END,
                  precision_m = CASE WHEN :better THEN CAST(:precision_m AS real)
                                     ELSE precision_m END
                WHERE id = :id
                """
            ),
            {
                "id": incident_id,
                "cell": signal.cell_id,
                "at": signal.observed_at,
                "rarity": signal.rarity,
                "signal": json.dumps([signal_as_json(signal)]),
                "better": better,
                "latitude": location.latitude if location else None,
                "longitude": location.longitude if location else None,
                "precision_m": location.precision_m if location else None,
                "location_method": location.method if location else None,
            },
        )
        session.commit()
    return incident_by_id(incident_id)


def merge_incidents(
    cause_id: str, effect_id: str, link: dict[str, Any]
) -> dict[str, Any] | None:
    """Absorb one incident into another, recording why.

    The cause keeps its id, because that is the incident anyone is already
    watching — a fire that acquires a smoke plume is still that fire. The
    effect is closed rather than deleted, so the id someone may already be
    holding still resolves and says where it went.
    """
    effect = incident_by_id(effect_id)
    if effect is None:
        return None

    with Session() as session:
        session.execute(
            text(
                """
                UPDATE incidents SET
                  hazards = ARRAY(SELECT DISTINCT unnest(hazards || CAST(:hazards AS text[]))),
                  queues  = ARRAY(SELECT DISTINCT unnest(queues  || CAST(:queues  AS text[]))),
                  cells   = ARRAY(SELECT DISTINCT unnest(cells   || CAST(:cells   AS text[]))),
                  last_signal_at = GREATEST(last_signal_at, :last_signal_at),
                  signal_count = signal_count + :signal_count,
                  peak_rarity = GREATEST(coalesce(peak_rarity, 0), coalesce(:peak_rarity, 0)),
                  signals = signals || CAST(:signals AS jsonb),
                  links   = links   || CAST(:link    AS jsonb)
                WHERE id = :id
                """
            ),
            {
                "id": cause_id,
                "hazards": effect["hazards"],
                "queues": effect["queues"],
                "cells": effect["cells"],
                "last_signal_at": effect["last_signal_at"],
                "signal_count": effect["signal_count"],
                "peak_rarity": effect["peak_rarity"],
                "signals": json.dumps(effect["signals"]),
                "link": json.dumps([link]),
            },
        )
        session.execute(
            text(
                """
                UPDATE incidents
                SET status = :closed, closed_at = now(),
                    links = links || CAST(:link AS jsonb)
                WHERE id = :id
                """
            ),
            {
                "id": effect_id,
                "closed": CLOSED,
                "link": json.dumps([{**link, "merged_into": cause_id}]),
            },
        )
        session.commit()
    return incident_by_id(cause_id)


def close_incident(incident_id: str, at: datetime) -> None:
    with Session() as session:
        with session.begin():
            closed_id = session.execute(
                text(
                    "UPDATE incidents SET status = :closed, closed_at = :at "
                    "WHERE id = :id AND status = :open RETURNING id"
                ),
                {"id": incident_id, "closed": CLOSED, "open": OPEN, "at": at},
            ).scalar_one_or_none()
            if closed_id is not None:
                release_incident_allocations_in_session(
                    session,
                    incident_id,
                    released_at=at,
                    reason="incident_closed",
                )


def close_quiet(at: datetime, quiet_period_for) -> list[str]:
    """Close every open incident nothing has seen for its own quiet period.

    Takes the per-hazard period as a callable rather than a constant, because
    a fire and an air-quality episode go quiet on very different clocks and
    one number for both would either split the slow one or merge the fast one.
    """
    closed = []
    for incident in open_incidents():
        if at - incident["last_signal_at"] > quiet_period_for(incident["primary_hazard"]):
            close_incident(incident["id"], at)
            closed.append(incident["id"])
    return closed
