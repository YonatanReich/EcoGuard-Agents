"""Operator feedback on handled incidents, and the improvement agent's reports.

Handling an incident does two things in one transaction: it freezes what the
operator saw into a feedback row and closes the incident. Either both happen or
neither does, so a feedback row always describes an incident that really was
handled, and a handled incident never goes missing from the record.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ecoguard.coordinator.incidents import close_incident_in_session
from ecoguard.database.engine import Session


def _json(value: Any) -> str:
    """JSON text for a jsonb parameter. Timestamps become ISO strings."""
    return json.dumps(value, default=str, ensure_ascii=False)


def record_handled(
    incident_id: str,
    *,
    handled_by: str,
    feedback: dict[str, Any] | None,
    code_version: str | None,
    at: datetime,
) -> int | None:
    """Snapshot an open incident, store the operator's feedback, close it.

    The snapshot is taken under a row lock, so a pipeline wave cannot attach a
    signal or rewrite the plan between the read and the close: the stored
    snapshot is exactly the incident that was handled.

    Args:
        feedback: The survey answers, or None when the operator closed the
            survey without filling it in.
        code_version: The commit the backend is running, so a report can tie a
            change in the numbers to a change in the code.

    Returns:
        int | None: The feedback row id, or None when there is no open incident
            with that id (already handled, or closed by going quiet).
    """
    with Session() as session:
        with session.begin():
            incident = session.execute(
                text("SELECT * FROM incidents WHERE id = :id AND status = 'open' FOR UPDATE"),
                {"id": incident_id},
            ).mappings().first()
            if incident is None:
                return None

            projection = session.execute(
                text(
                    "SELECT hazard, route, processing_status, analysis_status, "
                    "       planner_status, failure_stage, failure_reason, "
                    "       attempt_count, event_payload, "
                    "       last_successful_event_payload "
                    "FROM event_projections WHERE incident_id = :id"
                ),
                {"id": incident_id},
            ).mappings().first()

            snapshot = {
                # The incident as the coordinator stored it. `signals` is the
                # evidence: every detection, report and reading it was built from.
                "incident": dict(incident),
                # The event as the dashboard drew it: details, assessment and
                # response plan. Falls back to the last good payload, which is
                # what the dashboard shows when the latest attempt failed.
                "event": (
                    (projection["event_payload"] or projection["last_successful_event_payload"])
                    if projection else None
                ),
                "processing": (
                    {
                        key: projection[key]
                        for key in projection.keys()
                        if key not in ("event_payload", "last_successful_event_payload")
                    }
                    if projection else None
                ),
            }

            feedback_id = session.execute(
                text(
                    "INSERT INTO operator_feedback "
                    "  (kind, incident_id, submitted_at, submitted_by, code_version, "
                    "   feedback, snapshot) "
                    "VALUES ('handled', :incident_id, :at, :by, :version, "
                    "        CAST(:feedback AS jsonb), CAST(:snapshot AS jsonb)) "
                    "RETURNING id"
                ),
                {
                    "incident_id": incident_id,
                    "at": at,
                    "by": handled_by,
                    "version": code_version,
                    "feedback": _json(feedback) if feedback is not None else None,
                    "snapshot": _json(snapshot),
                },
            ).scalar_one()

            close_incident_in_session(session, incident_id, at)
    return feedback_id


def record_general(
    comment: str, *, submitted_by: str, code_version: str | None, at: datetime
) -> int:
    """Store free-text feedback about the system, not tied to any incident."""
    with Session() as session:
        with session.begin():
            return session.execute(
                text(
                    "INSERT INTO operator_feedback "
                    "  (kind, submitted_at, submitted_by, code_version, feedback) "
                    "VALUES ('general', :at, :by, :version, CAST(:feedback AS jsonb)) "
                    "RETURNING id"
                ),
                {
                    "at": at,
                    "by": submitted_by,
                    "version": code_version,
                    "feedback": _json({"text": comment}),
                },
            ).scalar_one()


def feedback_between(after: datetime | None, until: datetime) -> list[dict[str, Any]]:
    """Every feedback row, of both kinds, submitted in (after, until], oldest first.

    `after=None` means from the beginning, which is what the first report wants:
    every row nothing has reported on yet.
    """
    with Session() as session:
        rows = session.execute(
            text(
                "SELECT * FROM operator_feedback "
                "WHERE (CAST(:after AS timestamptz) IS NULL OR submitted_at > :after) "
                "  AND submitted_at <= :until "
                "ORDER BY submitted_at, id"
            ),
            {"after": after, "until": until},
        ).mappings().all()
    return [dict(row) for row in rows]


def feedback_by_id(feedback_id: int) -> dict[str, Any] | None:
    """One feedback row, snapshot included, or None."""
    with Session() as session:
        row = session.execute(
            text("SELECT * FROM operator_feedback WHERE id = :id"),
            {"id": feedback_id},
        ).mappings().first()
    return dict(row) if row else None


def feedback_trends(days: int) -> list[dict[str, Any]]:
    """Daily counts and average ratings per hazard over the last `days` days.

    Handled incidents only; general feedback has no hazard and no ratings.

    Computed in SQL rather than by the model, so the numbers in a report are
    counted, not estimated.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with Session() as session:
        rows = session.execute(
            text(
                """
                SELECT date_trunc('day', submitted_at)::date                AS day,
                       snapshot->'incident'->>'primary_hazard'               AS hazard,
                       count(*)                                              AS handled,
                       count(*) FILTER (WHERE feedback IS NULL)              AS survey_skipped,
                       count(*) FILTER (WHERE feedback->>'verdict' = 'real')         AS real,
                       count(*) FILTER (WHERE feedback->>'verdict' = 'false_report') AS false_report,
                       count(*) FILTER (WHERE feedback->>'verdict' = 'duplicate')    AS duplicate,
                       round(avg((feedback->>'plan_rating')::numeric), 2)    AS avg_plan_rating,
                       round(avg((feedback->>'details_rating')::numeric), 2) AS avg_details_rating,
                       round(avg(extract(epoch FROM submitted_at
                             - (snapshot->'incident'->>'first_seen_at')::timestamptz) / 60))
                                                                             AS avg_minutes_open
                FROM operator_feedback
                WHERE kind = 'handled' AND submitted_at >= :since
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            ),
            {"since": since},
        ).mappings().all()
    return [dict(row) for row in rows]


def insert_report(
    *,
    window_start: datetime | None,
    window_end: datetime,
    feedback_count: int,
    model: str,
    report: dict[str, Any],
) -> int:
    """Store one finished report and return its id."""
    with Session() as session:
        with session.begin():
            return session.execute(
                text(
                    "INSERT INTO improvement_reports "
                    "  (window_start, window_end, feedback_count, model, report) "
                    "VALUES (:start, :end, :count, :model, CAST(:report AS jsonb)) "
                    "RETURNING id"
                ),
                {
                    "start": window_start,
                    "end": window_end,
                    "count": feedback_count,
                    "model": model,
                    "report": _json(report),
                },
            ).scalar_one()


def recent_reports(limit: int) -> list[dict[str, Any]]:
    """The newest reports first."""
    with Session() as session:
        rows = session.execute(
            text("SELECT * FROM improvement_reports ORDER BY created_at DESC LIMIT :limit"),
            {"limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]
