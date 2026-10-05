"""Reading and writing incidents, the coordinator's only stored state.

Returns plain dictionaries rather than database rows, so nothing else in the
coordinator has to know how they are stored.

Signals are kept in a list on the incident itself rather than a separate table.
The list stays bounded because an incident closes once it goes quiet, and every
query here reads the incident as a whole.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import text

from ecoguard.database.engine import Session
from ecoguard.database.repositories.resource_allocations import (
    release_incident_allocations_in_session,
)
from ecoguard.shared.signals import CellSignal

OPEN = "open"
CLOSED = "closed"

# How the text lane marks a location it geocoded from a place name.
TEXT_LOCATION_METHOD = "text_report_gazetteer"

_COLUMNS = """
    id, status, primary_hazard, hazards, queues, cells,
    latitude, longitude, precision_m, location_method,
    first_seen_at, last_signal_at, closed_at,
    signal_count, peak_rarity, links, signals,
    confirmed_at, confirmed_by
"""

# What a write hands back: everything matching needs, without `signals` and
# `links`. The signal history grows with every signal and nothing on the
# coordinator's path reads it; returning it from each write made a 40-signal
# advisory cost more per signal the longer it ran. Read the full row with
# `incident_by_id` when the history is wanted.
_MATCH_COLUMNS = """
    id, status, primary_hazard, hazards, queues, cells,
    latitude, longitude, precision_m, location_method,
    first_seen_at, last_signal_at, closed_at,
    signal_count, peak_rarity, confirmed_at, confirmed_by
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
    """One database row as a plain incident dict.

    Normalises the array columns to lists so callers never have to care which
    driver returned them.
    """
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

    Highest existing number plus one, not a count: once any row of the day is
    gone (INC-20261004-0011 was), count + 1 lands on an id still in use and
    every new incident that day fails on the primary key.
    """
    day = at.astimezone(timezone.utc).strftime("%Y%m%d")
    with Session() as session:
        highest = session.execute(
            text("SELECT max(id) FROM incidents WHERE id LIKE :prefix"),
            {"prefix": f"INC-{day}-%"},
        ).scalar_one()
    used = int(highest.rsplit("-", 1)[1]) if highest else 0
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
    """One incident by id, or None when there is no such row."""
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
        row = session.execute(
            text(
                f"""
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
                RETURNING {_MATCH_COLUMNS}
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
        ).mappings().first()
        session.commit()
    # RETURNING rather than a second read: one round trip per signal saved.
    return _row(row) if row else None


def is_better_fix(location, current: dict[str, Any]) -> bool:
    """Whether this fix should replace the incident's stored location.

    Smaller radius wins, with one exception: a text geocode never beats an
    instrument fix, whatever the radii say. A town's radius describes the town,
    not the fire - ynet's "near Isfiya" is a 520 m circle on the village, the
    MODIS pixel 3 km west is the fire, and letting the smaller number win moved
    the Carmel incident onto houses and its fuel lookup onto built-up ground.
    """
    if location is None:
        return False
    stored_precision = current.get("precision_m")
    if stored_precision is None:
        return True
    incoming_is_text = location.method == TEXT_LOCATION_METHOD
    stored_is_text = current.get("location_method") == TEXT_LOCATION_METHOD
    if stored_is_text != incoming_is_text:
        return stored_is_text
    return location.precision_m < stored_precision


def merged_incident(current: dict[str, Any], signal: CellSignal) -> dict[str, Any]:
    """The incident after one more sighting, computed without the database.

    The one statement of how a signal folds in, used both to keep the
    coordinator's in-memory view current within a batch and to write the
    batch. The location only improves: a better fix replaces a worse one and a
    worse one is ignored, never averaged - averaging a 375 m satellite pixel
    with a 2 km town-name geocode produces a place neither source suggested.
    `last_signal_at` only advances, so a late-arriving old reading - routine
    with FIRMS, which runs hours behind the overpass - cannot drag an incident
    backwards and make it look quiet.
    """
    merged = dict(current)
    cells = list(current.get("cells") or [])
    if signal.cell_id not in cells:
        cells.append(signal.cell_id)
    merged["cells"] = cells
    last = current.get("last_signal_at")
    merged["last_signal_at"] = signal.observed_at if last is None else max(last, signal.observed_at)
    merged["signal_count"] = int(current.get("signal_count") or 0) + 1
    if signal.rarity is not None:
        merged["peak_rarity"] = max(float(current.get("peak_rarity") or 0.0), signal.rarity)
    location = signal.location
    if is_better_fix(location, current):
        merged.update(
            latitude=location.latitude,
            longitude=location.longitude,
            precision_m=location.precision_m,
            location_method=location.method,
        )
    return merged


def attach_signal(
    incident_id: str,
    signal: CellSignal,
    *,
    current: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Fold another sighting into an incident that already exists."""
    return attach_signals(incident_id, [signal], current=current)


def attach_signals(
    incident_id: str,
    signals: Sequence[CellSignal],
    *,
    current: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Fold several sightings into one incident in a single write.

    A batch routinely carries many signals for one incident - forty hourly
    fire-weather readings for one advisory on the historical fire replay - and
    one UPDATE each, at three round trips to a database ~165 ms away, was the
    largest part of coordination. The merge is computed in Python by
    `merged_incident` and written once; `signal_count`, `peak_rarity` and
    `last_signal_at` are still combined with the stored row in SQL, so the write
    stays correct even if the row moved since `current` was read.
    """
    if not signals:
        return current
    # The coordinator passes the row it matched against, saving a read.
    current = current or incident_by_id(incident_id)
    if current is None:
        return None
    merged = current
    for signal in signals:
        merged = merged_incident(merged, signal)

    with Session() as session:
        row = session.execute(
            text(
                f"""
                UPDATE incidents SET
                  cells = ARRAY(
                    SELECT DISTINCT unnest(cells || CAST(:cells AS text[]))
                  ),
                  last_signal_at = GREATEST(last_signal_at, :at),
                  signal_count = signal_count + :count,
                  peak_rarity = GREATEST(coalesce(peak_rarity, 0), coalesce(:rarity, 0)),
                  signals = signals || CAST(:signals AS jsonb),
                  latitude = CAST(:latitude AS double precision),
                  longitude = CAST(:longitude AS double precision),
                  location_method = CAST(:location_method AS text),
                  precision_m = CAST(:precision_m AS real)
                WHERE id = :id
                RETURNING {_MATCH_COLUMNS}
                """
            ),
            {
                "id": incident_id,
                "cells": merged["cells"],
                "at": merged["last_signal_at"],
                "count": len(signals),
                "rarity": max((s.rarity for s in signals if s.rarity is not None), default=None),
                "signals": json.dumps([signal_as_json(signal) for signal in signals]),
                "latitude": merged.get("latitude"),
                "longitude": merged.get("longitude"),
                "precision_m": merged.get("precision_m"),
                "location_method": merged.get("location_method"),
            },
        ).mappings().first()
        session.commit()
    return _row(row) if row else None


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
    """Close one open incident and release the stations held against it.

    Does nothing when the incident is already closed, so repeating the call is
    safe.
    """
    with Session() as session:
        with session.begin():
            close_incident_in_session(session, incident_id, at)


def close_incident_in_session(session, incident_id: str, at: datetime) -> bool:
    """`close_incident` inside a caller's transaction.

    For a caller whose own write must commit or fail together with the close,
    such as the operator-feedback row written when an incident is handled.

    Returns:
        bool: True when this call closed the incident, False when it was
            already closed or does not exist.
    """
    closed_id = session.execute(
        text(
            "UPDATE incidents SET status = :closed, closed_at = :at "
            "WHERE id = :id AND status = :open RETURNING id"
        ),
        {"id": incident_id, "closed": CLOSED, "open": OPEN, "at": at},
    ).scalar_one_or_none()
    if closed_id is None:
        return False
    release_incident_allocations_in_session(
        session,
        incident_id,
        released_at=at,
        reason="incident_closed",
    )
    return True


def confirm_incident(
    incident_id: str, at: datetime, by: str = "operator"
) -> dict[str, Any] | None:
    """Record that a person checked this incident and it is real.

    Returns the updated incident, or None when there is no open incident with
    that id — a closed one is not confirmed after the fact, because the decision
    it records is about a response that is no longer running.

    The first confirmation wins: `confirmed_at IS NULL` in the predicate means a
    second click does not move the timestamp, so "when was this confirmed" keeps
    answering the question it was asked.
    """
    with Session() as session:
        with session.begin():
            session.execute(
                text(
                    "UPDATE incidents SET confirmed_at = :at, confirmed_by = :by "
                    "WHERE id = :id AND status = :open AND confirmed_at IS NULL"
                ),
                {"id": incident_id, "at": at, "by": by, "open": OPEN},
            )
            row = session.execute(
                text(f"SELECT {_COLUMNS} FROM incidents WHERE id = :id AND status = :open"),
                {"id": incident_id, "open": OPEN},
            ).mappings().one_or_none()
    return _row(row) if row is not None else None


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
