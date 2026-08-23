from unittest.mock import MagicMock, patch

import requests

from agents.weather_data_agent import WeatherDataAgent


def assert_failed_without_weather(result: dict, error: str) -> None:
    assert result["metadata"]["collection_status"] == "failed"
    assert result["error"] == error
    assert result["weather"] == {"current": {}, "forecast": {"daily": {}}}


@patch("agents.weather_data_agent.requests.get")
def test_weather_timeout_returns_structured_failure(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("provider URL")

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert_failed_without_weather(result, "timeout")
    assert mock_get.call_args.kwargs["timeout"] == 15


@patch("agents.weather_data_agent.requests.get")
def test_weather_request_exception_returns_structured_failure(mock_get):
    mock_get.side_effect = requests.exceptions.RequestException("network down")

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert_failed_without_weather(result, "network error")


@patch("agents.weather_data_agent.requests.get")
def test_malformed_weather_json_returns_structured_failure(mock_get):
    response = MagicMock()
    response.json.side_effect = ValueError("invalid JSON")
    mock_get.return_value = response

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert_failed_without_weather(result, "malformed response")


@patch("agents.weather_data_agent.requests.get")
def test_missing_weather_fields_returns_structured_failure(mock_get):
    response = MagicMock()
    response.json.return_value = {"current": {}, "daily": {}}
    mock_get.return_value = response

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert_failed_without_weather(result, "malformed response")


@patch("agents.weather_data_agent.requests.get")
def test_unexpected_weather_parsing_error_returns_structured_failure(mock_get):
    response = MagicMock()
    response.json.side_effect = RuntimeError("unexpected parser failure")
    mock_get.return_value = response

    result = WeatherDataAgent().fetch_weather_data(31.9, 34.8)

    assert_failed_without_weather(result, "unexpected provider error")
