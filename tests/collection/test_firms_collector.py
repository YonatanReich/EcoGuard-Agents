"""FIRMS parsing and grouping, against a recorded API response."""

from datetime import datetime, timezone
from pathlib import Path

from agents.firms_data_agent import FirmsDataAgent
from ecoguard.collection.base import cell_for
from ecoguard.collection.firms import FirmsCollector, group_hotspots

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "firms_hotspots.csv"


def _hotspots():
    return FirmsDataAgent().parse_hotspots_csv(FIXTURE.read_text(encoding="utf-8"))


def test_pixels_sharing_a_cell_and_overpass_become_one_observation():
    records = group_hotspots(_hotspots())

    daytime = [r for r in records if r["observed_at"].hour == 10]
    assert len(daytime) == 1
    assert daytime[0]["payload"]["hotspot_count"] == 2
    assert daytime[0]["observed_at"] == datetime(2026, 9, 6, 10, 42, tzinfo=timezone.utc)


def test_a_later_overpass_of_the_same_cell_is_a_separate_observation():
    records = group_hotspots(_hotspots())
    cells = {record["cell_id"] for record in records}

    assert len(cells) == 1                    # both Jerusalem pixels, one cell
    assert len(records) == 2                  # two overpasses
    assert {r["observed_at"].hour for r in records} == {10, 22}


def test_hotspots_outside_the_service_area_are_dropped():
    # The bounding box overshoots into Egypt; that Cairo row must not be stored.
    assert cell_for(30.0444, 31.2357) is None
    stored = [h for record in group_hotspots(_hotspots()) for h in record["payload"]["hotspots"]]
    assert all(h["longitude"] > 34 for h in stored)
    assert len(stored) == 3


def test_the_service_area_is_swept_in_one_request():
    calls = []

    class _Agent:
        def fetch_hotspots(self, **kwargs):
            calls.append(kwargs)
            return {"fire_satellite_data": {"hotspots": _hotspots()}}

    records = FirmsCollector(agent=_Agent()).fetch()

    assert len(calls) == 1
    assert calls[0]["delta"] > 1.5            # covers the country, not a point
    assert len(records) == 2
