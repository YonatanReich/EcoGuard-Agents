"""The agent reads the store and never invents a reading.

It used to call Open-Meteo per request; these now patch the store read instead
of `requests.get`. The property under test is unchanged and is the one every
caller depends on: whatever goes wrong, the agent returns the same shape with
collection_status "failed" rather than raising or fabricating weather.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from agents.weather_data_agent import WeatherDataAgent

READ = "agents.weather_data_agent.current_for_point"
OBSERVED_AT = datetime(2026, 9, 10, 1, tzinfo=timezone.utc)


def reading(**overrides):
    return {
        "cell_id": "risk-05000m-r0010-c0010",
        "observed_at": OBSERVED_AT,
        "latitude": 31.9,
        "longitude": 34.8,
        "distance_m": 812.4,
        "temperature_2m": 24.4,
        "relative_humidity_2m": 68.0,
        "wind_speed_10m": 3.1,
        "wind_direction_10m": 127.0,
        "wind_gusts_10m": 7.2,
        "precipitation": 0.0,
        "rain": 0.0,
        "weather_code": 3.0,
        **overrides,
    }


def assert_failed_without_weather(result: dict, error: str) -> None:
    assert result["metadata"]["collection_status"] == "failed"
    assert result["error"] == error
    assert result["weather"] == {"current": {}, "forecast": {"daily": {}}}


@patch(READ)
def test_a_stored_reading_is_served_in_the_unified_shape(read):
    read.return_value = reading()

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert result["metadata"]["collection_status"] == "success"
    assert result["weather"]["current"] == {
        "temperature_c": 24.4,
        "humidity_percent": 68.0,
        "wind_speed_kmh": 3.1,
        "precipitation_mm": 0.0,
        # Stored as a float alongside the other hourly values; the WMO code is
        # an integer and callers read it as one.
        "weather_code": 3,
    }
    assert result["location"] == {"latitude": 31.9, "longitude": 34.8}


@patch(READ)
def test_the_answering_cell_is_reported_because_a_grid_answered_a_point(read):
    read.return_value = reading()

    metadata = WeatherDataAgent().fetch_weather_data(31.9, 34.8)["metadata"]["observation"]

    assert metadata["cell_id"] == "risk-05000m-r0010-c0010"
    assert metadata["distance_m"] == 812.4
    assert metadata["observed_at"] == OBSERVED_AT.isoformat()


@patch(READ)
def test_no_forecast_is_offered_because_the_store_holds_observations(read):
    read.return_value = reading()

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert result["weather"]["forecast"] == {"daily": {}}


@patch(READ)
def test_a_coordinate_with_no_recent_reading_fails_rather_than_guessing(read):
    # Outside the collected grid, or collection has been down for hours. Both
    # mean there is no observation, and the old behaviour - reach out and get
    # one - is exactly what this refactor removed.
    read.return_value = None

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert_failed_without_weather(result, "no recent observation for this location")


@patch(READ)
def test_an_unreachable_store_returns_a_structured_failure(read):
    read.side_effect = OperationalError("SELECT 1", {}, Exception("connection refused"))

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert_failed_without_weather(result, "observation store unavailable")


@patch(READ)
def test_an_unexpected_error_still_does_not_propagate(read):
    read.side_effect = RuntimeError("something nobody predicted")

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert_failed_without_weather(result, "unexpected store error")


@patch(READ)
def test_a_missing_variable_stays_null_rather_than_becoming_zero(read):
    # A null temperature is "we do not know", and zero degrees is a reading.
    read.return_value = reading(temperature_2m=None, weather_code=None)

    current = WeatherDataAgent().fetch_weather_data(31.9, 34.8)["weather"]["current"]

    assert current["temperature_c"] is None
    assert current["weather_code"] is None
