"""Read-only shared-data availability checks for Air Pollution verification."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session


def latest_firms_collector_run() -> dict[str, Any] | None:
    """Return the latest shared FIRMS collection attempt without fetching data."""

    with Session() as session:
        row = session.execute(text(
            "SELECT source, started_at, finished_at, status, rows_written, error "
            "FROM collector_runs WHERE source = 'firms' "
            "ORDER BY started_at DESC LIMIT 1"
        )).mappings().first()
    return dict(row) if row else None
