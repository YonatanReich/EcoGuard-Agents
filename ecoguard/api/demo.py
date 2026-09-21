"""Demo event feed — the live dashboard, fed from a separate database.

Exists so the resource allocator, the response plans and the event modals can
be shown working without waiting for something to actually happen in Israel.
Everything here is fabricated, which is why it is kept in its own database and
behind its own route: nothing in the demo store can reach /api/events, and
nothing real can reach this one.

The rows carry whole SharedEvent payloads rather than a normalized schema.
The contract the frontend reads is that payload, so a demo that stores it
verbatim can never drift from the shape the dashboard expects — and it is
validated on the way out anyway.

Seed it with `python -m ecoguard.scripts.seed_demo`.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import TypeAdapter
from sqlalchemy import create_engine, text

from ecoguard.shared.events import SharedEvent, SharedEventFeed

logger = logging.getLogger(__name__)
router = APIRouter()
_event_adapter = TypeAdapter(SharedEvent)


@lru_cache(maxsize=1)
def _engine():
    # Not inherited from database.engine: that module owns the live store and
    # raises at import when DATABASE_URL is missing.
    load_dotenv()
    url = os.getenv("DEMO_DATABASE_URL")
    if not url:
        raise RuntimeError("DEMO_DATABASE_URL is not set")
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


@router.get("/api/demo/events", response_model=SharedEventFeed)
def get_demo_events() -> SharedEventFeed:
    try:
        with _engine().connect() as connection:
            rows = connection.execute(text(
                "SELECT payload FROM demo_events ORDER BY position, id"
            )).mappings().all()
    except Exception as error:
        logger.exception("Unable to read the demo event store")
        raise HTTPException(
            status_code=503, detail="Demo event feed is unavailable"
        ) from error

    return SharedEventFeed(
        events=[_event_adapter.validate_python(row["payload"]) for row in rows]
    )
