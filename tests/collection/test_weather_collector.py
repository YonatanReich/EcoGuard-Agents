"""The weather collector stores observations, never the rest of the forecast."""

from datetime import datetime, timezone

from ecoguard.collection.base import service_area_cells
from ecoguard.collection.weather import WeatherCollector, records_from_batch
from services.open_meteo_hourly_client import HOURLY_VARIABLES


def _response(hours):
    return {
        "hourly": {
            "time": [hour.isoformat() for hour in hours],
            **{variable: list(range(len(hours))) for variable in HOURLY_VARIABLES},
        }
    }


def test_hours_at_or_after_the_current_hour_are_dropped_as_forecast():
    hours = [datetime(2026, 9, 6, hour, tzinfo=timezone.utc) for hour in range(6)]
    cell = service_area_cells()[0]

    records = records_from_batch(
        [cell], [_response(hours)], before=datetime(2026, 9, 6, 3, tzinfo=timezone.utc)
    )

    assert [record["observed_at"].hour for record in records] == [0, 1, 2]
    assert all(record["cell_id"] == cell.cell_id for record in records)
    assert set(records[0]["payload"]) == set(HOURLY_VARIABLES)


def test_every_service_area_cell_is_requested_in_batches():
    requested = []

    class _Client:
        batch_size = 50

        def fetch_range(self, coordinates, start, end):
            requested.extend(coordinates)
            return [_response([]) for _ in coordinates]

    WeatherCollector(client=_Client()).fetch()

    assert len(requested) == len(service_area_cells())


def test_hours_older_than_the_lookback_window_are_dropped_as_already_stored():
    hours = [datetime(2026, 9, 6, hour, tzinfo=timezone.utc) for hour in range(12)]
    cell = service_area_cells()[0]

    records = records_from_batch(
        [cell],
        [_response(hours)],
        before=datetime(2026, 9, 6, 10, tzinfo=timezone.utc),
        since=datetime(2026, 9, 6, 8, tzinfo=timezone.utc),
    )

    assert [record["observed_at"].hour for record in records] == [8, 9]
