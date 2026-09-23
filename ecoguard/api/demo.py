"""The demo event feed, served from its own database.

Lets the allocator, the response plans and the event cards be shown working
without waiting for something to actually happen. Everything here is
fabricated, which is why it lives in a separate database behind a separate
route: nothing demo can reach the live feed, and nothing real can reach this
one."""

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
    """A connection to the demo database, which is kept separate from the live one."""
    # Not inherited from database.engine: that module owns the live store and
    # raises at import when DATABASE_URL is missing.
    load_dotenv()
    url = os.getenv("DEMO_DATABASE_URL")
    if not url:
        raise RuntimeError("DEMO_DATABASE_URL is not set")
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


@router.get("/api/demo/events", response_model=SharedEventFeed)
def get_demo_events() -> SharedEventFeed:
    """The demo events, in the same shape the dashboard reads for real ones."""
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
