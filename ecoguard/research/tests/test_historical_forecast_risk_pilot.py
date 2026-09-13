from datetime import datetime, timezone

from research.pilots.build_historical_forecast_risk_pilot import (
    deterioration, forecast_indicators, load_pilot_rows, select_available_run, validate_forecast,
)


def _forecast(run, hours=24):
    times = [(run.replace(tzinfo=None) + __import__('datetime').timedelta(hours=index)).isoformat(timespec='minutes') for index in range(hours)]
    return {"timezone": "GMT", "hourly": {"time": times, "temperature_2m": [30 + i / 10 for i in range(hours)], "relative_humidity_2m": [40 - i / 2 for i in range(hours)], "precipitation": [0] * hours, "wind_speed_10m": [10 + i for i in range(hours)], "wind_gusts_10m": [20 + i for i in range(hours)]}}


def test_selected_run_was_available_by_evaluation_time():
    evaluation = datetime(2025, 8, 24, 5, 28, tzinfo=timezone.utc)
    run = select_available_run(evaluation)
    assert run == datetime(2025, 8, 23, 18, 0, tzinfo=timezone.utc)
    assert run + __import__('datetime').timedelta(hours=6) <= evaluation


def test_forecast_target_is_future_and_comes_from_archived_run():
    run = datetime(2025, 8, 23, 18, tzinfo=timezone.utc)
    forecast = validate_forecast(_forecast(run), run)
    evaluation = datetime(2025, 8, 24, 5, 28, tzinfo=timezone.utc)
    event = datetime(2025, 8, 24, 11, 28, tzinfo=timezone.utc)
    values = forecast_indicators(forecast, evaluation, event)
    assert evaluation < event
    assert values["forecast_target_time"] == "2025-08-24T11:00:00+00:00"
    assert values["forecast_temperature_event"] == 31.7


def test_realized_future_observations_and_event_label_are_not_inputs():
    current = {"temperature_1h_before": 25, "humidity_1h_before": 50, "wind_speed_1h_before": 8, "precipitation_1h_before": 0}
    forecast = {"forecast_temperature_event": 30, "forecast_humidity_event": 35, "forecast_wind_speed_event": 20, "forecast_precipitation_sum_to_event": 0}
    result = deterioration(current, forecast)
    assert result["forecast_environmental_risk_signal"] == "material_worsening"
    assert result["forecast_risk_score"] == ""
    assert "fire_label" not in result
    assert all("observed_future" not in key for key in result)


def test_no_material_change_is_not_called_fire_probability():
    current = {"temperature_1h_before": 30, "humidity_1h_before": 30, "wind_speed_1h_before": 20, "precipitation_1h_before": 0}
    forecast = {"forecast_temperature_event": 30, "forecast_humidity_event": 30, "forecast_wind_speed_event": 20, "forecast_precipitation_sum_to_event": 0}
    result = deterioration(current, forecast)
    assert result["forecast_environmental_risk_signal"] == "no_material_worsening"
    assert result["forecast_risk_status"] == "not_calculated_no_forecast_trained_or_calibrated_model"


def test_loader_uses_retained_t0_as_actual_event_time(tmp_path):
    import csv
    path = tmp_path / "trajectory.csv"
    rows = [
        {"original_event_id": "event", "source_type": "verified_telegram", "trajectory_offset_hours": "-3", "evaluation_reference_time": "2025-01-01T09:00:00+00:00"},
        {"original_event_id": "event", "source_type": "verified_telegram", "trajectory_offset_hours": "0", "evaluation_reference_time": "2025-01-01T12:00:00+00:00"},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    selected = load_pilot_rows(path)
    assert selected[0]["actual_event_timestamp"] == "2025-01-01T12:00:00+00:00"


def test_pilot_does_not_train_model_or_consume_event_firms_evidence():
    import inspect
    import research.pilots.build_historical_forecast_risk_pilot as module
    source = inspect.getsource(module)
    assert ".fit(" not in source
    assert "FireRiskPredictionAgent" not in source
    assert "firms_candidate" not in source.lower()
