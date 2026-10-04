"""Incidents are analysed in parallel; one incident's facets are not."""

import threading
import time
from datetime import datetime, timezone

from ecoguard.coordinator.dispatcher import dispatch_incidents
from ecoguard.coordinator.incidents import signal_as_json
from ecoguard.shared.signals import FIRE, HIGH, CellSignal

AT = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
DELAY = 0.3


def _incident(identifier, *, hybrid=False):
    fire = signal_as_json(CellSignal(
        cell_id="risk-05000m-r0053-c0015", observed_at=AT, hazard=FIRE, variable="frp",
        value=150.0, unit="MW", source="firms", rarity=1.0, direction=HIGH,
    ))
    return {
        "id": identifier, "status": "open", "primary_hazard": FIRE,
        "hazards": [FIRE, "air_pollution"] if hybrid else [FIRE],
        "queues": ["emergency", "non_emergency"] if hybrid else ["emergency"],
        "signals": [fire], "latitude": 31.81, "longitude": 35.0,
    }


class SlowHandler:
    """Stands in for two model calls: slow, and records who overlapped whom."""

    def __init__(self, name, active):
        self.name = name
        self.active = active

    def process(self, incident, context):
        with self.active["lock"]:
            self.active.setdefault(incident["id"], 0)
            self.active[incident["id"]] += 1
            self.active["max_same_incident"] = max(
                self.active.get("max_same_incident", 0), self.active[incident["id"]]
            )
        time.sleep(DELAY)
        with self.active["lock"]:
            self.active[incident["id"]] -= 1
        return f"{incident['id']}:{context.hazard}"


def _dispatch(incidents, active):
    registry = {
        ("fire", "emergency"): SlowHandler("fire", active),
        ("air_pollution", "non_emergency"): SlowHandler("air", active),
    }
    return dispatch_incidents(
        incidents, registry=registry, at=AT, projection_reader=lambda _id: None,
    )


def test_three_fires_take_the_time_of_one_not_three():
    active = {"lock": threading.Lock()}
    started = time.monotonic()
    results = _dispatch([_incident("A"), _incident("B"), _incident("C")], active)
    elapsed = time.monotonic() - started

    assert results == ["A:fire", "B:fire", "C:fire"]  # order kept
    assert elapsed < DELAY * 2


def test_one_incidents_facets_never_run_at_once():
    # Both facets write the same projection row.
    active = {"lock": threading.Lock()}
    results = _dispatch([_incident("H", hybrid=True), _incident("A")], active)

    assert results == ["H:fire", "H:air_pollution", "A:fire"]
    assert active["max_same_incident"] == 1
