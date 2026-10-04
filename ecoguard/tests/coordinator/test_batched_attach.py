"""Many signals for one incident are written once, not once each."""

from datetime import datetime, timedelta, timezone

from ecoguard.coordinator.agent import coordinate
from ecoguard.coordinator.incidents import merged_incident
from ecoguard.shared.signals import FIRE, HIGH, CellLocation, CellSignal

AT = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
CELL = "risk-05000m-r0053-c0015"


def _signal(minutes, *, precision=3000.0, cell=CELL):
    return CellSignal(
        cell_id=cell, observed_at=AT + timedelta(minutes=minutes), hazard=FIRE,
        variable="frp", value=50.0, unit="MW", source="firms", rarity=1.0, direction=HIGH,
        location=CellLocation(31.81, 35.0, precision, "frp_weighted_centroid"),
    )


class Store:
    def __init__(self):
        self.rows = {}
        self.writes = []

    def close_quiet(self, now, quiet_period_for):
        return []

    def open_incidents(self, hazards=None):
        return [dict(row) for row in self.rows.values()]

    def next_incident_id(self, now):
        return f"INC-{len(self.rows) + 1}"

    def create_incident(self, incident_id, signal, queues):
        self.rows[incident_id] = {
            "id": incident_id, "status": "open", "primary_hazard": signal.hazard,
            "hazards": [signal.hazard], "queues": list(queues), "cells": [signal.cell_id],
            "latitude": signal.location.latitude, "longitude": signal.location.longitude,
            "precision_m": signal.location.precision_m,
            "location_method": signal.location.method,
            "first_seen_at": signal.observed_at, "last_signal_at": signal.observed_at,
            "signal_count": 1, "peak_rarity": signal.rarity, "links": [], "signals": [],
        }
        return dict(self.rows[incident_id])

    def attach_signals(self, incident_id, signals, *, current=None):
        self.writes.append((incident_id, len(signals)))
        row = current
        for signal in signals:
            row = merged_incident(row, signal)
        self.rows[incident_id] = row
        return row

    def merge_incidents(self, *args):
        raise AssertionError("nothing to merge")


def test_forty_signals_for_one_incident_are_one_write():
    store = Store()
    coordinate([_signal(minute) for minute in range(41)], at=AT, incident_store=store)
    assert list(store.rows) == ["INC-1"]
    assert store.writes == [("INC-1", 40)]
    assert store.rows["INC-1"]["signal_count"] == 41
    assert store.rows["INC-1"]["last_signal_at"] == AT + timedelta(minutes=40)


def test_the_merge_keeps_the_better_fix_and_never_moves_time_backwards():
    row = {"cells": [CELL], "last_signal_at": AT, "signal_count": 1,
           "precision_m": 3000.0, "location_method": "frp_weighted_centroid"}
    finer = merged_incident(row, _signal(-30, precision=375.0, cell="other"))
    assert finer["precision_m"] == 375.0
    assert finer["last_signal_at"] == AT
    assert finer["cells"] == [CELL, "other"]
