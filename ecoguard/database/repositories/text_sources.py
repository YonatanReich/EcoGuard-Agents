"""Reads of the curated text-source allowlist, and the polling cursor.

Tier is read from here and from nowhere else. Nothing in the pipeline may
derive it from a channel name, a feed domain, or anything a model returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.database.engine import Session

AUTHORITY = "authority"
MEDIA = "media"
UNOFFICIAL = "unofficial"

# Which path a tier feeds. Media joins the official path: a report from an
# established outlet creates an event without corroboration.
OFFICIAL_TIERS = frozenset({AUTHORITY, MEDIA})


@dataclass(frozen=True)
class TextSource:
    source_id: str
    kind: str
    handle: str
    display_name: str | None
    tier: str
    hazards: tuple[str, ...]
    peer_id: int | None
    last_message_id: int | None
    last_polled_at: datetime | None
    etag: str | None
    last_modified: str | None

    @property
    def official(self) -> bool:
        return self.tier in OFFICIAL_TIERS

    @property
    def never_polled(self) -> bool:
        return self.last_polled_at is None

    def conditional_headers(self) -> dict[str, str]:
        """What to send so an unchanged feed answers 304 instead of a body."""
        headers = {}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        return headers


def _row(row) -> TextSource:
    return TextSource(
        source_id=row["source_id"],
        kind=row["kind"],
        handle=row["handle"],
        display_name=row["display_name"],
        tier=row["tier"],
        hazards=tuple(row["hazards"] or ()),
        peer_id=row["peer_id"],
        last_message_id=row["last_message_id"],
        last_polled_at=row["last_polled_at"],
        etag=row["etag"],
        last_modified=row["last_modified"],
    )


def active_sources(kind: str | None = None) -> list[TextSource]:
    """Every active source, optionally narrowed to 'telegram' or 'rss'."""
    query = "SELECT * FROM text_sources WHERE active"
    params: dict[str, Any] = {}
    if kind is not None:
        query += " AND kind = :kind"
        params["kind"] = kind
    query += " ORDER BY handle"
    with Session() as session:
        return [_row(row) for row in session.execute(text(query), params).mappings()]


def tier_for(source_id: str) -> str | None:
    """The tier of one source, or None when it is not on the allowlist.

    None is not a tier and must never be treated as `unofficial`: a message
    from a source nobody curated is a configuration error, and silently
    admitting it at the weakest tier would hide that.
    """
    with Session() as session:
        return session.execute(
            text("SELECT tier FROM text_sources WHERE source_id = :id"),
            {"id": source_id},
        ).scalar_one_or_none()


def record_poll(
    source_id: str,
    *,
    last_message_id: int | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    at: datetime | None = None,
) -> None:
    """Record a successful read: the cursor, and the conditional-poll tokens.

    The message cursor only ever moves forward. A provider that replays an old
    page must not drag it backwards and cause the same window to be re-read on
    every tick afterwards.

    The ETag and Last-Modified are overwritten rather than merged, including
    with NULL: a feed that stops sending an ETag has withdrawn it, and echoing
    a stale one back would ask about a version the server no longer knows.
    """
    with Session() as session:
        session.execute(
            text(
                """
                UPDATE text_sources
                   SET last_polled_at = :at,
                       etag = :etag,
                       last_modified = :last_modified,
                       last_message_id = GREATEST(
                         COALESCE(last_message_id, 0), COALESCE(:message_id, 0)
                       )
                 WHERE source_id = :id
                """
            ),
            {
                "id": source_id,
                "at": at or datetime.now(timezone.utc),
                "etag": etag,
                "last_modified": last_modified,
                "message_id": last_message_id,
            },
        )
        session.commit()
