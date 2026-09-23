"""The collector fetches the gap, never a fixed window, and never a forecast.

The fixed six-hour lookback it replaced could only repair outages shorter than
itself: a nine-hour outage left three hours that nothing would ever go back
for, and production had thirteen such hours in a sixty-seven-hour span. These
pin the behaviour that fixed it.
"""

from datetime import datetime, timedelta, timezone

import pytest

import ecoguard.collectors.shared.open_meteo.observations as weather_module
from ecoguard.collectors.base import service_area_cells
from ecoguard.collectors.shared.open_meteo.observations import WeatherCollector, plan_fetches, records_from_batch
from ecoguard.collectors.shared.open_meteo.client import HOURLY_VARIABLES, HourlyProviderError

UTC = timezone.utc


def _response(hours):
    return {
        "hourly": {
            "time": [hour.isoformat() for hour in hours],
            **{variable: list(range(len(hours))) for variable in HOURLY_VARIABLES},
        }
    }


class _Client:
    batch_size = 50

    def __init__(self, hours=(), fail_after=None):
        self.hours = list(hours)
        self.fail_after = fail_after
        self.calls = []

    def fetch_range(self, coordinates, start, end):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise HourlyProviderError("rate_limited", transient=False)
        self.calls.append((list(coordinates), start, end))
        return [_response(self.hours) for _ in coordinates]


def _hours(*values):
    return [datetime(2026, 9, 6, value, tzinfo=UTC) for value in values]


# --- what gets stored -------------------------------------------------------

def test_hours_at_or_after_the_current_hour_are_dropped_as_forecast():
    cell = service_area_cells()[0]

    records = records_from_batch(
        [cell], [_response(_hours(0, 1, 2, 3, 4, 5))], before=datetime(2026, 9, 6, 3, tzinfo=UTC)
    )

    assert [record["observed_at"].hour for record in records] == [0, 1, 2]
    assert all(record["cell_id"] == cell.cell_id for record in records)
    assert set(records[0]["payload"]) == set(HOURLY_VARIABLES)


# --- what gets requested ----------------------------------------------------

def test_cells_missing_the_same_hour_collapse_into_shared_batches():
    gaps = {f"cell-{index:03d}": _hours(9) for index in range(120)}

    planned = plan_fetches(gaps, batch_size=50, request_budget=99)

    assert len(planned) == 3                      # 120 cells / 50
    assert {window for window, _ in planned} == {(_hours(9)[0], _hours(9)[0])}
    assert sum(len(cells) for _, cells in planned) == 120


def test_consecutive_missing_hours_become_one_request_not_one_each():
    planned = plan_fetches({"cell-a": _hours(1, 2, 3, 4)}, batch_size=50, request_budget=99)

    assert planned == [((_hours(1)[0], _hours(4)[0]), ["cell-a"])]


def test_a_hole_between_stored_hours_is_fetched_as_its_own_range():
    planned = plan_fetches({"cell-a": _hours(1, 2, 7, 8)}, batch_size=50, request_budget=99)

    assert sorted(window for window, _ in planned) == [
        (_hours(1)[0], _hours(2)[0]),
        (_hours(7)[0], _hours(8)[0]),
    ]


def test_the_budget_keeps_the_newest_gaps_and_defers_the_backfill():
    # A cold start wants seven days at once. Firing all of it is how the
    # collector talked itself into sustained 429s, so a tick is bounded and the
    # recent hours - the ones every consumer actually reads - go first.
    planned = plan_fetches({"cell-a": _hours(1, 3, 5, 7, 9)}, batch_size=50, request_budget=2)

    assert [window[1].hour for window, _ in planned] == [9, 7]


# --- the collector as a whole ----------------------------------------------

def test_nothing_missing_means_no_provider_call_at_all(monkeypatch):
    monkeypatch.setattr(weather_module, "missing_hours", lambda *args, **kwargs: {})
    client = _Client()

    assert WeatherCollector(client=client).fetch() == []
    assert client.calls == []


def test_only_the_missing_hours_are_requested(monkeypatch):
    cell = service_area_cells()[0]
    gap = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=4)
    monkeypatch.setattr(weather_module, "missing_hours", lambda *args, **kwargs: {cell.cell_id: [gap]})
    client = _Client(hours=[gap])

    records = WeatherCollector(client=client).fetch()

    assert len(client.calls) == 1
    coordinates, start, end = client.calls[0]
    assert coordinates == [(cell.latitude, cell.longitude)]
    assert start == end == gap
    assert [record["observed_at"] for record in records] == [gap]


def test_a_gap_longer_than_the_old_lookback_window_is_still_repaired(monkeypatch):
    # Nine hours. The six-hour window this replaced would have abandoned three
    # of them permanently.
    current = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    gap = [current - timedelta(hours=offset) for offset in range(9, 0, -1)]
    cell = service_area_cells()[0]
    monkeypatch.setattr(weather_module, "missing_hours", lambda *args, **kwargs: {cell.cell_id: gap})
    client = _Client(hours=gap)

    records = WeatherCollector(client=client).fetch()

    assert len(client.calls) == 1
    assert client.calls[0][1] == gap[0] and client.calls[0][2] == gap[-1]
    assert [record["observed_at"] for record in records] == gap


def test_the_budget_counts_cell_hours_because_that_is_what_the_provider_charges():
    """A request can carry one hour or a hundred and sixty-eight.

    Counting requests let a cold-start tick ask for 93,450 cell-hours on 21
    requests while a steady-state tick of 24 asked for 1,174 — a hundredfold
    swing under a budget that saw both as "fine". The wide one was rate limited.
    """
    long_gap = [_hours(0)[0] + timedelta(hours=step) for step in range(100)]
    gaps = {f"cell-{index:03d}": list(long_gap) for index in range(500)}

    planned = plan_fetches(gaps, batch_size=50, cell_hour_budget=25_000, request_budget=99)

    spent = sum(
        (int((window[1] - window[0]).total_seconds() // 3600) + 1) * len(cells)
        for window, cells in planned
    )
    assert spent <= 25_000
    # 100 hours x 50 cells = 5,000 per request, so five fit and the rest wait.
    assert len(planned) == 5


def test_one_oversized_batch_still_goes_rather_than_stalling_forever():
    huge = [_hours(0)[0] + timedelta(hours=step) for step in range(168)]

    planned = plan_fetches({"cell-a": huge}, batch_size=50, cell_hour_budget=10, request_budget=99)

    assert len(planned) == 1


def test_a_rate_limited_tick_keeps_the_batches_that_already_succeeded(monkeypatch):
    """The loop that made the rate limiting self-sustaining.

    Letting the provider error propagate discarded the whole tick, so a run cut
    off on its ninth request threw away the eight that had worked, asked for
    exactly the same data next tick, and was cut off again.
    """
    current = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    gap = [current - timedelta(hours=2)]
    cells = service_area_cells()[:120]
    monkeypatch.setattr(
        weather_module, "missing_hours", lambda *a, **k: {cell.cell_id: list(gap) for cell in cells}
    )
    client = _Client(hours=gap, fail_after=2)

    records = WeatherCollector(client=client).fetch()

    assert len(client.calls) == 2          # third raised
    assert len(records) == 100             # two batches of fifty, kept
    assert {record["observed_at"] for record in records} == set(gap)


def test_a_tick_that_fetches_nothing_at_all_still_fails_loudly(monkeypatch):
    # Partial results are worth keeping; zero results are an outage, and the
    # reason has to reach collector_runs instead of being logged as a success.
    current = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    cell = service_area_cells()[0]
    monkeypatch.setattr(
        weather_module, "missing_hours",
        lambda *a, **k: {cell.cell_id: [current - timedelta(hours=2)]},
    )

    with pytest.raises(HourlyProviderError):
        WeatherCollector(client=_Client(fail_after=0)).fetch()
