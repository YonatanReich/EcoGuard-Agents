"""FIRMS parsing and grouping, against a recorded API response."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ecoguard.collectors.fire.firms.client import FirmsDataAgent, FirmsProviderError
from ecoguard.collectors.base import cell_for
from ecoguard.collectors.fire.firms.collector import SOURCES, FirmsCollector, group_hotspots

# Found by walking up rather than counting parents: this file has already moved
# once during a restructure, and a hard-coded depth breaks silently when it does.
FIXTURES = next(
    parent / "fixtures"
    for parent in Path(__file__).resolve().parents
    if (parent / "fixtures").is_dir()
)
FIXTURE = FIXTURES / "firms_hotspots.csv"


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


def test_each_satellite_sweeps_the_service_area_in_one_request():
    calls = []

    class _Agent:
        def fetch_hotspots(self, **kwargs):
            calls.append(kwargs)
            return {"fire_satellite_data": {"hotspots": _hotspots()}}

    records = FirmsCollector(agent=_Agent()).fetch()

    # One request per satellite product, not per cell: the API takes an area,
    # so each product is asked for the area once.
    assert len(calls) == len(SOURCES)
    assert {call["source"] for call in calls} == set(SOURCES)
    assert all(call["delta"] > 1.5 for call in calls)   # the country, not a point

    # Four products returning the same two overpasses is still two overpasses.
    # Grouping is by cell and time, so the satellites merge rather than
    # multiply — getting this wrong would report four times the fire.
    assert len(records) == 2
    assert records[0]["payload"]["satellite_sources"] == sorted(SOURCES)


def test_one_failing_satellite_does_not_lose_the_others():
    class _Agent:
        def fetch_hotspots(self, **kwargs):
            if kwargs["source"] == "MODIS_NRT":
                raise RuntimeError("provider 503")
            return {"fire_satellite_data": {"hotspots": _hotspots()}}

    records = FirmsCollector(agent=_Agent()).fetch()

    assert len(records) == 2
    assert "MODIS_NRT" not in records[0]["payload"]["satellite_sources"]


def test_every_satellite_failing_is_a_collection_failure():
    # Distinct from "no hotspots today": nothing was observed either way, but
    # only one of those is an outage, and a silent empty result would read as
    # a quiet country.
    class _Agent:
        def fetch_hotspots(self, **kwargs):
            raise RuntimeError("provider 503")

    with pytest.raises(FirmsProviderError):
        FirmsCollector(agent=_Agent()).fetch()
