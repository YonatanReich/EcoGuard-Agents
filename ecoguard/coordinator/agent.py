"""The coordinator: signals in, two queues of incidents out.

Every detector for every hazard feeds this one entry point, which is what makes
it event-agnostic — it knows `CellSignal` and nothing about fire, floods or
smog. Adding a hazard means adding a detector and a row in the queue table, not
touching anything here.

One run, five steps, in this order for reasons:

  1. **Close what has gone quiet.** Before matching, so a signal arriving after
     a long silence starts a new incident rather than resurrecting a stale one.
  2. **Load what is open.**
  3. **Match or create**, per signal. This is the deduplication: a fire raging
     for three days lands forty signals on one incident instead of forty
     incidents.
  4. **Package** causally linked incidents into hybrids — a fire and the
     pollution downwind of it become one event with two hazards.
  5. **Queue.** Emergency and advisory, built last so a hybrid created in step
     four lands in both.

Packaging runs after matching, not during, because a link can only be judged
once both sides exist as incidents. A pollution signal arriving before the fire
is seen is not yet linkable to anything; it becomes its own incident and is
absorbed on a later run, when the fire it belongs to exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from ecoguard.coordinator import incidents as store
from ecoguard.coordinator.matching import best_match, has_gone_quiet, quiet_period_for
from ecoguard.coordinator.packaging import causal_link
from ecoguard.coordinator.queues import EMERGENCY, NON_EMERGENCY, UnroutableHazard, queues_for
from ecoguard.database.locks import single_flight
from ecoguard.database.repositories.collector_runs import log_finish, log_start
from ecoguard.shared.signals import CellSignal

logger = logging.getLogger(__name__)

SOURCE = "coordinator"


@dataclass
class CoordinationResult:
    """What one run did, without having to query the table to find out."""

    emergency: list[dict[str, Any]] = field(default_factory=list)
    non_emergency: list[dict[str, Any]] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    linked: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    @property
    def touched(self) -> int:
        """Incidents this run created or changed."""
        return len(self.touched_ids)

    @property
    def touched_ids(self) -> list[str]:
        """Final incident identities affected, including hybrid merge causes."""
        identifiers = [*self.created, *self.updated]
        identifiers.extend(
            link["cause_incident"]
            for link in self.linked
            if link.get("cause_incident")
        )
        return list(dict.fromkeys(identifiers))


def coordinate(
    signals: Sequence[CellSignal],
    *,
    at: datetime | None = None,
    incident_store=None,
) -> CoordinationResult:
    """Fold a batch of signals into incidents and return the two queues.

    Args:
        signals: everything the detectors produced this tick, any hazard mixed
            together. Order does not matter; they are sorted by time so an
            incident's first signal is genuinely its earliest.
        at: treat this as now. Defaults to the wall clock; passing it makes a
            run reproducible and lets tests drive the quiet-period logic
            without sleeping.
        incident_store: Optional repository implementing the production
            incident-store contract. The default remains PostgreSQL; the
            explicit manual-test path supplies an in-memory implementation.

    Returns:
        CoordinationResult. The queues hold incident dicts, not signals — one
        entry per thing that is happening, which is the whole point.
    """
    selected_store = incident_store or store
    now = at or datetime.now(timezone.utc)
    result = CoordinationResult()

    result.closed = selected_store.close_quiet(now, quiet_period_for)

    for signal in sorted(signals, key=lambda s: s.observed_at):
        try:
            queues = queues_for([signal.hazard])
        except UnroutableHazard as error:
            # A hazard nobody has routed cannot be queued, and guessing would
            # put it somewhere nobody is watching. Record it and carry on: one
            # unroutable detector must not stop the others being coordinated.
            logger.warning("coordinator: %s", error)
            result.skipped.append({"signal": signal, "reason": str(error)})
            continue

        open_now = selected_store.open_incidents(hazards=[signal.hazard])
        match = best_match(signal, open_now)
        if match is None:
            incident_id = selected_store.next_incident_id(now)
            selected_store.create_incident(incident_id, signal, queues)
            result.created.append(incident_id)
        else:
            selected_store.attach_signal(match["id"], signal)
            result.updated.append(match["id"])

    result.linked = _package(now, incident_store=selected_store)

    for incident in selected_store.open_incidents():
        if EMERGENCY in incident["queues"]:
            result.emergency.append(incident)
        if NON_EMERGENCY in incident["queues"]:
            result.non_emergency.append(incident)

    return result


def _package(at: datetime, *, incident_store=None) -> list[dict[str, Any]]:
    """Merge every open incident that was plausibly caused by another.

    Quadratic over open incidents, which is fine: the country produces a
    handful at a time, and the quiet-period sweep keeps the open set small. If
    that stops being true the fix is to index candidates by cell rather than to
    weaken the check.

    Re-reads the open set on every merge because merging closes one incident
    and widens another — continuing against a stale list would try to absorb
    something already absorbed.
    """
    selected_store = incident_store or store
    links: list[dict[str, Any]] = []
    merged: set[str] = set()

    for _ in range(len(selected_store.open_incidents())):
        candidates = [
            i for i in selected_store.open_incidents() if i["id"] not in merged
        ]
        joined = False
        for cause in candidates:
            for effect in candidates:
                if cause["id"] == effect["id"]:
                    continue
                link = causal_link(cause, effect)
                if link is None:
                    continue
                selected_store.merge_incidents(cause["id"], effect["id"], link)
                merged.add(effect["id"])
                links.append(link)
                joined = True
                break
            if joined:
                break
        if not joined:
            break

    return links


def run(signals: Sequence[CellSignal] | None = None) -> CoordinationResult | None:
    """Coordinate once, recording the outcome like any other scheduled job.

    Never raises, for the same reason the collectors do not: a failed
    coordination run leaves incidents un-merged until the next tick, which is
    survivable, while an exception out of a scheduler thread is not.

    Holds `single_flight` across the whole run because the incident updates are
    read-modify-write — two concurrent runs could both decide a signal starts a
    new incident and create two for one event, which is exactly the duplication
    this stage exists to prevent.
    """
    try:
        with single_flight(f"coordinate_{SOURCE}") as acquired:
            if not acquired:
                logger.info("coordinator: previous run still going, skipping tick")
                return
            run_id = log_start(SOURCE)
            try:
                result = coordinate(signals or [])
                log_finish(run_id, status="ok", rows_written=result.touched)
                logger.info(
                    "coordinator: %s created, %s updated, %s closed, %s linked; "
                    "queues %s emergency / %s advisory",
                    len(result.created), len(result.updated), len(result.closed),
                    len(result.linked), len(result.emergency), len(result.non_emergency),
                )
                return result
            except Exception as error:
                log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
                logger.exception("coordinator failed")
    except Exception:
        # The database itself is unreachable, so there is nowhere to record a
        # failure. Log and return; the next tick tries again.
        logger.exception("coordinator could not reach the database")
    return None
