"""When people-in-danger figures and evacuation orders may be shown.

Found on a Telegram fire report in Givat Shmuel: the card said "Evacuate now:
Givat Shmuel" and that 18 people were in the forecast spread of a town of about
25,000. Touches no database.
"""

from datetime import datetime, timezone

import pytest

from ecoguard.analyzers.fire import environment as fire_environment
from ecoguard.analyzers.fire import spread_analyzer
from ecoguard.analyzers.fire.incident_handler import without_unconfirmed_claims
from ecoguard.coordinator.event_projection import _with_confirmation
from ecoguard.shared.events import (
    FireDetails,
    FireEvacuationDirective,
    FireExposedSettlement,
    FireSharedEvent,
)

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
RING = [[34.85, 32.07], [34.86, 32.07], [34.86, 32.08], [34.85, 32.07]]


def incident(source, variable):
    return {
        "id": "INC-20261005-0001",
        "primary_hazard": "fire",
        "latitude": 32.077,
        "longitude": 34.852,
        "confirmed_at": None,
        "signals": [{"hazard": "fire", "source": source, "variable": variable, "observed_at": NOW}],
    }


@pytest.fixture
def analyse(monkeypatch):
    """Run analyze_incident with the model stubbed, returning the ring count it was given."""
    passes = []
    monkeypatch.setattr(
        spread_analyzer, "analyze",
        lambda incident, environment, **options: passes.append(options)
        or {"status": "ok", "spread": {"likely": RING}},
    )
    monkeypatch.setattr(fire_environment, "history_for", lambda incident: None)
    monkeypatch.setattr(fire_environment, "population_within", lambda ring: {"people": 18})

    def run(built_up_fraction):
        spread_analyzer.analyze_incident(
            incident("firms", "frp"),
            environment={"built_up_fraction": built_up_fraction},
            localities=[],
        )
        return passes[-1]["ring_population"]

    return run


def test_wildland_ring_is_not_counted_on_built_up_ground(analyse):
    # The ring models vegetation only; inside a town it is a few metres of
    # garden, and its grid share is not the people a structure fire endangers.
    assert analyse(0.8) is None


def test_wildland_ring_is_counted_on_open_ground(analyse):
    assert analyse(0.1) == {"people": 18}


def fire_event():
    return FireSharedEvent.model_construct(
        id="INC-20261005-0001",
        details=FireDetails(
            people_in_spread=18,
            population_at_risk={"likely": 25000},
            evacuation=[FireEvacuationDirective(
                name="Givat Shmuel", priority="immediate", population=25000, reason="in the spread",
            )],
            exposed_settlements=[FireExposedSettlement(
                name="Givat Shmuel", population=25000, exposure="burning",
            )],
        ),
    )


def test_unconfirmed_report_carries_no_people_count():
    event = _with_confirmation(fire_event(), incident("fireisrael", "report"))

    assert event.confirmation.status == "unconfirmed"
    assert event.details.people_in_spread is None
    assert event.details.population_at_risk == {}
    assert event.details.evacuation == []
    assert event.details.exposed_settlements[0].population is None


def test_instrument_confirmed_fire_keeps_its_count():
    event = _with_confirmation(fire_event(), incident("firms", "frp"))

    assert event.confirmation.status == "confirmed"
    assert event.details.people_in_spread == 18
    assert event.details.evacuation[0].name == "Givat Shmuel"


def test_unconfirmed_fire_analysis_reaches_the_risk_model_without_orders():
    detected = {"event_type": "fire", "spread_forecast": {
        "status": "ok",
        "spread": {"likely": RING},
        "evacuation": [{"name": "Givat Shmuel", "priority": "immediate"}],
        "population_in_spread": {"people": 18},
        "population_at_risk": {"burning": 25000},
        "exposure": [{"name": "Givat Shmuel", "population": 25000, "exposure": "burning"}],
        "headline": "Fire burning in Givat Shmuel",
        "report": "PEOPLE AT RISK",
    }}

    spread = without_unconfirmed_claims(detected)["spread_forecast"]

    assert spread["spread"] == {"likely": RING}  # the shape to check stays
    assert spread["evacuation"] == []
    assert spread["population_in_spread"] is None
    assert spread["exposure"][0] == {"name": "Givat Shmuel", "population": None, "exposure": "burning"}
    assert spread["report"] is None and spread["headline"] is None
