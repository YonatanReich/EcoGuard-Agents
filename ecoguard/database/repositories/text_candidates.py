"""Writing classifier output, and reading back what triage will need."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import text

from ecoguard.database.engine import Session


def store_candidates(results: Sequence[dict[str, Any]]) -> int:
    """One row per message per hazard. Returns rows written or corrected.

    A message the classifier found no hazard in writes nothing. That is not a
    negative record — it is the absence of a claim, and storing a row per
    hazard per non-hazard message would be four rows of nothing for every
    football result in the feed.

    Re-classifying corrects in place, because the identity of a candidate is
    the message and the hazard, not the run that produced it.
    """
    rows = []
    for result in results:
        for hazard in result.get("hazards") or ():
            rows.append({
                "observation_id": result["observation_id"],
                "source_id": result["source_id"],
                "hazard": hazard,
                "relevant": bool(result["relevant"]),
                "literal": bool(result["literal"]),
                "in_israel": bool(result["in_israel"]),
                "update_type": result.get("update_type") or "none",
                "location_text": result.get("location_text"),
                "claim": result.get("claim"),
                "details": json.dumps(
                    (result.get("details") or {}).get(hazard, {}), ensure_ascii=False
                ),
                "classified_by": result["classified_by"],
                "model_version": result.get("model_version"),
                "keyword_matched": hazard in set(result.get("keyword_hazards") or ()),
                "observed_at": result["observed_at"],
            })
    if not rows:
        return 0

    with Session() as session:
        written = session.execute(
            text(
                """
                INSERT INTO text_candidates (
                  observation_id, source_id, hazard, relevant, literal,
                  in_israel, update_type, location_text, claim, details,
                  classified_by, model_version, keyword_matched, observed_at
                ) VALUES (
                  :observation_id, :source_id, :hazard, :relevant, :literal,
                  :in_israel, :update_type, :location_text, :claim,
                  CAST(:details AS jsonb),
                  :classified_by, :model_version, :keyword_matched, :observed_at
                )
                ON CONFLICT ON CONSTRAINT text_candidates_identity DO UPDATE SET
                  relevant = EXCLUDED.relevant,
                  literal = EXCLUDED.literal,
                  in_israel = EXCLUDED.in_israel,
                  update_type = EXCLUDED.update_type,
                  location_text = EXCLUDED.location_text,
                  claim = EXCLUDED.claim,
                  details = EXCLUDED.details,
                  classified_by = EXCLUDED.classified_by,
                  model_version = EXCLUDED.model_version,
                  keyword_matched = EXCLUDED.keyword_matched
                RETURNING id
                """
            ),
            rows,
        ).rowcount
        session.commit()
    return written or 0


def unclassified_text_observations(
    *, since: datetime, limit: int = 500
) -> list[dict[str, Any]]:
    """Stored messages with no candidate row and no record of being judged.

    The cursor is the row itself, not a clock: a message is unclassified when
    nothing in `text_candidates` points at it. That survives a crash halfway
    through a batch, and it means a model outage does not silently skip the
    messages that arrived during it — they are still unclassified on the next
    tick.

    The trade is that a message the classifier read and found nothing in looks
    identical to one it never read, so it is offered again. `since` bounds
    that: re-reading yesterday's football results forever would be the cost of
    having no negative rows.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT o.id AS observation_id,
                       o.observed_at,
                       o.payload->>'source_id' AS source_id,
                       o.payload->>'handle' AS handle,
                       o.payload->>'display_name' AS display_name,
                       o.payload->>'raw_text' AS text
                  FROM observations o
                 WHERE o.source IN ('telegram', 'rss')
                   AND o.ingested_at > :since
                   AND o.payload->>'source_id' IS NOT NULL
                   AND NOT EXISTS (
                         SELECT 1 FROM text_candidates c
                          WHERE c.observation_id = o.id
                       )
                 ORDER BY o.observed_at DESC
                 LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]


def recent_candidates(
    hazard: str, *, at: datetime, window: timedelta
) -> list[dict[str, Any]]:
    """Reportable candidates for one hazard in a window, newest first.

    Filtered to what triage can act on: a relevant, literal, in-country claim.
    The tier is joined rather than stored, so a source re-tiered this morning
    is read at its new tier this afternoon.
    """
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT c.*, s.tier, s.handle, s.display_name, o.payload
                  FROM text_candidates c
                  JOIN text_sources s ON s.source_id = c.source_id
                  JOIN observations o ON o.id = c.observation_id
                 WHERE c.hazard = :hazard
                   AND c.relevant AND c.literal AND c.in_israel
                   AND c.observed_at BETWEEN :since AND :at
                 ORDER BY c.observed_at DESC
                """
            ),
            {"hazard": hazard, "at": at, "since": at - window},
        ).mappings().all()
    return [dict(row) for row in rows]
