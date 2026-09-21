"""Bounded, source-scoped reads of raw Telegram observations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ecoguard.database.engine import Session
from ecoguard.database.models import Observation


TELEGRAM_SOURCE = "telegram"
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must carry a UTC offset")
    return value.astimezone(timezone.utc)


def telegram_observation_statement(
    *, observed_since: datetime, observed_through: datetime, limit: int = DEFAULT_LIMIT
):
    since = _utc(observed_since, "observed_since")
    through = _utc(observed_through, "observed_through")
    if since > through:
        raise ValueError("observed_since cannot exceed observed_through")
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    return (
        select(
            Observation.id,
            Observation.source,
            Observation.cell_id,
            Observation.observed_at,
            Observation.ingested_at,
            Observation.payload,
        )
        .where(
            Observation.source == TELEGRAM_SOURCE,
            Observation.observed_at >= since,
            Observation.observed_at <= through,
        )
        .order_by(Observation.observed_at, Observation.id)
        .limit(limit)
    )


def recent_telegram_observations(
    *, observed_since: datetime, observed_through: datetime, limit: int = DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    statement = telegram_observation_statement(
        observed_since=observed_since,
        observed_through=observed_through,
        limit=limit,
    )
    with Session() as session:
        return [dict(row) for row in session.execute(statement).mappings().all()]
