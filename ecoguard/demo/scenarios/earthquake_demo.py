"""Replay the 24 August 1984 Jezreel Valley earthquake from GSI evidence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.collectors.earthquake.gsi import SOURCE
from ecoguard.database.engine import Session
from ecoguard.shared.cells import cell_for

SCHEMA = "earthquake_demo"
EVENT_ID = "gsi198408240602"
EPICENTRE = (32.65079498, 35.19147491)
SOURCE_URL = (
    "https://seis.gsi.gov.il/fdsnws/event/1/query"
    "?format=text&eventid=gsi198408240602"
)

# Original GSI catalogue values, embedded like the other scenario inputs.
HISTORICAL_EVENT: dict[str, Any] = {
    "provider_event_id": EVENT_ID,
    "observed_at": "1984-08-24T06:02:25.358+00:00",
    "latitude": EPICENTRE[0],
    "longitude": EPICENTRE[1],
    "magnitude": 5.347415924,
    "depth_km": 12.0,
    "provider": "GSI",
    "raw": {
        "event_id": EVENT_ID,
        "author": "autoloc",
        "catalog": None,
        "contributor": "GSI",
        "contributor_id": EVENT_ID,
        "magnitude_type": "Md",
        "magnitude_author": "autoloc",
        "event_location_name": "",
        "event_type": "earthquake",
    },
}

GROUND_TRUTH: list[dict[str, Any]] = [{
    "id": "EQ1",
    "event": "Jezreel Valley earthquake, 24 August 1984 (GSI Md 5.35, depth 12 km).",
    "hazard": "earthquake",
    "latitude": EPICENTRE[0],
    "longitude": EPICENTRE[1],
    "expect_detected": True,
    "expect_route": "emergency",
    "expect_marker_within_km": 0.1,
    "expect_min_signals": 1,
    "expect_notes": (
        "One real GSI catalogue record, with an epicentre on land near Kfar "
        "Barooch. Only its timestamp is rebased. Magnitude exceeds the 3.5 "
        "dashboard threshold. The current model estimates MMI VI within "
        "7.13 km, V within 26.27 km and IV within 58.49 km. The outer "
        "extent includes light shaking and is not a damage boundary. "
        "Detection, impact analysis, planning, allocation and routing run "
        "normally. This is a catalogue replay, not an early-warning test."
    ),
}]
EXPECTED_BYPRODUCTS: list[dict[str, str]] = []
EXPECTED_SILENCE: list[dict[str, str]] = []


def build_rows(now: datetime) -> list[tuple[str, str, datetime, dict[str, Any]]]:
    """Build collector-shaped rows from the embedded historical observation."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("demo start time must include a timezone")
    cell_id = cell_for(HISTORICAL_EVENT["latitude"], HISTORICAL_EVENT["longitude"])
    if cell_id is None:
        raise ValueError("earthquake demo epicentre is outside the operational grid")
    observed_at = now.astimezone(timezone.utc) - timedelta(minutes=5)
    payload = {
        **HISTORICAL_EVENT,
        "observed_at": observed_at.isoformat(),
        "raw": {
            **HISTORICAL_EVENT["raw"],
            "demo_replay": {
                "scenario": SCHEMA,
                "historical_observed_at": HISTORICAL_EVENT["observed_at"],
                "source_url": SOURCE_URL,
                "retrieved_on": "2026-10-04",
            },
        },
    }
    return [(SOURCE, cell_id, observed_at, payload)]


def seed(schema: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Persist evidence only in earthquake_demo, regardless of the search path."""
    if schema != SCHEMA:
        raise ValueError(f"earthquake observations must be seeded into {SCHEMA}")
    moment = now or datetime.now(timezone.utc)
    rows = build_rows(moment)
    statement = text(
        'INSERT INTO "earthquake_demo".observations '
        "(source, cell_id, location, observed_at, ingested_at, payload) "
        "VALUES (:source, :cell_id, "
        "ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography, "
        ":observed_at, :ingested_at, CAST(:payload AS jsonb))"
    )
    with Session() as session:
        for source, cell_id, observed_at, payload in rows:
            session.execute(statement, {
                "source": source, "cell_id": cell_id,
                "latitude": payload["latitude"], "longitude": payload["longitude"],
                "observed_at": observed_at, "ingested_at": moment,
                "payload": json.dumps(payload, ensure_ascii=False),
            })
        session.commit()
    return {
        "observations": len(rows), "by_source": {SOURCE: len(rows)},
        "seeded_at": moment.isoformat(),
        "expectations": {"events": GROUND_TRUTH, "silence": EXPECTED_SILENCE},
    }
