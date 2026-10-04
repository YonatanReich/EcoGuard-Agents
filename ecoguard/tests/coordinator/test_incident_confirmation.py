"""Confirmation state, and the routing it no longer changes.

Touches no database: `confirmation_of` reads a dict, and `dispatch_incidents`
takes its registry and its projection reader as arguments.
"""

from datetime import datetime, timezone

from ecoguard.coordinator.confirmation import (
    INSTRUMENT,
    OPERATOR,
    confirmation_of,
)
from ecoguard.coordinator.dispatcher import (
    UNCORROBORATED_ROUTE,
    IncidentDispatchContext,
    IncidentProcessingResult,
    dispatch_incidents,
)

NOW = datetime(2025, 4, 23, 9, 0, tzinfo=timezone.utc)


def text_signal(source="ynet", corroborated=False):
    """A signal that came from somebody's say-so."""
    return {
        "hazard": "fire",
        "variable": "report",
        "source": source,
        "observed_at": NOW,
        "evidence": {"text_report": {
            "claim": "שריפה ביערות אשתאול",
            "location_text": "אשתאול",
            "corroborated": corroborated,
        }},
    }


def hotspot_signal():
    """A signal that something measured."""
    return {
        "hazard": "fire",
        "variable": "frp",
        "source": "firms",
        "observed_at": NOW,
        "evidence": {"pixels": [{"latitude": 31.79, "longitude": 35.02, "frp": 42.0}]},
    }


def incident(signals, **extra):
    """An open fire incident on the emergency queue."""
    return {
        "id": "incident-1",
        "status": "open",
        "primary_hazard": "fire",
        "hazards": ["fire"],
        "queues": ["emergency"],
        "cells": ["risk-05000m-r0052-c0015"],
        "latitude": 31.7908,
        "longitude": 35.0186,
        "signals": signals,
        **extra,
    }


# --- confirmation state -------------------------------------------------------

def test_instrument_evidence_confirms():
    state = confirmation_of(incident([hotspot_signal()]))
    assert state.confirmed is True
    assert state.basis == INSTRUMENT
    assert "firms" in state.detail


def test_text_alone_is_unconfirmed_even_when_corroborated():
    """Two newsrooms agreeing is worth more, but it is not a measurement."""
    state = confirmation_of(incident([
        text_signal("ynet", corroborated=True),
        text_signal("walla", corroborated=True),
    ]))
    assert state.confirmed is False
    assert state.basis is None


def test_operator_click_confirms():
    state = confirmation_of(incident(
        [text_signal()], confirmed_at=NOW, confirmed_by="duty officer"
    ))
    assert state.confirmed is True
    assert state.basis == OPERATOR
    assert state.confirmed_by == "duty officer"


def test_instrument_outranks_the_operator():
    """A hotspot that lands after the click is the stronger evidence."""
    state = confirmation_of(incident(
        [text_signal(), hotspot_signal()], confirmed_at=NOW, confirmed_by="duty officer"
    ))
    assert state.basis == INSTRUMENT


def test_no_signals_is_not_confirmed():
    assert confirmation_of(incident([])).confirmed is False


# --- routing ------------------------------------------------------------------

class RecordingHandler:
    """A handler that records the context it was given."""

    def __init__(self, name):
        self.name = name
        self.contexts: list[IncidentDispatchContext] = []

    def process(self, incident, context):
        self.contexts.append(context)
        return IncidentProcessingResult(
            incident_id=context.incident_id,
            hazard=context.hazard,
            route=context.route,
            status="success",
            requested_at=context.requested_at,
            completed_at=context.requested_at,
            handler=self.name,
        )


def dispatch(incident_row):
    """Dispatch one incident against stub handlers, with no plan on file."""
    fire = RecordingHandler("fire")
    advisory = RecordingHandler("advisory")
    results = dispatch_incidents(
        [incident_row],
        registry={("fire", "emergency"): fire, UNCORROBORATED_ROUTE: advisory},
        at=NOW,
        projection_reader=lambda _incident_id: None,
    )
    return fire, advisory, results


def test_unconfirmed_fire_reaches_the_fire_handler():
    """The regression this change exists to prevent: analysis was being skipped."""
    fire, advisory, results = dispatch(incident([text_signal()]))
    assert [r.handler for r in results] == ["fire"]
    assert advisory.contexts == []
    assert fire.contexts[0].confirmed is False
    assert fire.contexts[0].confirmation_basis is None


def test_confirmed_fire_reaches_the_fire_handler_too():
    fire, advisory, _ = dispatch(incident([hotspot_signal()]))
    assert advisory.contexts == []
    assert fire.contexts[0].confirmed is True
    assert fire.contexts[0].confirmation_basis == INSTRUMENT


def test_hazard_without_a_handler_still_gets_the_advisory():
    """Nothing regresses for a hazard this deployment has no analyser for.

    Flood is on the emergency route like fire, so the registry below is the only
    reason it has no handler — which is exactly the case the fallback is for.
    """
    row = incident([{**text_signal(), "hazard": "flood"}])
    row["hazards"] = ["flood"]
    row["primary_hazard"] = "flood"
    advisory = RecordingHandler("advisory")
    results = dispatch_incidents(
        [row],
        registry={UNCORROBORATED_ROUTE: advisory},
        at=NOW,
        projection_reader=lambda _incident_id: None,
    )
    assert [r.handler for r in results] == ["advisory"]
