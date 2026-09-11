import csv
from datetime import datetime, timedelta, timezone

from research.datasets.build_fire_prediction_ml_dataset import (
    FORBIDDEN_ML_FIELDS,
    ML_FEATURE_FIELDS,
    OUTPUT_FIELDS as UNIFIED_FIELDS,
    combine_datasets,
    summarize_dataset,
)
from research.datasets.build_historical_fire_weather_features import FEATURE_FIELDS, compute_features
from research.datasets.build_historical_negative_weather_features import (
    NEGATIVE_FIELDS,
    build_negative_feature_row,
    build_negative_weather_features,
)


EVENT_TIME = datetime(2024, 6, 15, 10, tzinfo=timezone.utc)


def negative(identifier="negative-1"):
    return {
        "negative_id": identifier,
        "reference_positive_candidate_id": "positive-1",
        "sample_timestamp": "2024-06-15T10:00:00Z",
        "latitude": "31.9",
        "longitude": "34.9",
        "settlement": "רמלה",
        "settlement_lamas_code": "8500",
        "sample_month": "6",
        "sample_hour": "10",
        "nearest_firms_candidate_distance_km": "0",
        "nearest_firms_candidate_time_gap_hours": "100",
        "official_month_support": "false",
        "sample_generation_method": "same_centroid_same_month",
        "fire_label": "0",
    }


def weather():
    start = EVENT_TIME - timedelta(hours=168)
    times = [(start + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M") for index in range(170)]
    values = list(range(170))
    values[-1] = 9999
    return {
        "status": "success",
        "missing_variables": [],
        "hourly": {
            "time": times,
            "temperature_2m": values,
            "relative_humidity_2m": [200 - value for value in values],
            "precipitation": [1] * 170,
            "rain": [0.5] * 170,
            "wind_speed_10m": values,
            "wind_direction_10m": [270] * 170,
            "wind_gusts_10m": values,
        },
    }


def positive_weather_row():
    row = {
        "candidate_id": "positive-1",
        "start_timestamp": "2024-06-14T10:00:00Z",
        "centroid_latitude": "31.9",
        "centroid_longitude": "34.9",
        "settlement": "רמלה",
        "settlement_lamas_code": "8500",
        "official_month_support": "true",
        "official_event_count": "1",
        "firms_candidates_same_settlement_month": "2",
        "ground_truth_status": "supported",
        "weather_source": "Open-Meteo Historical Weather API",
        "weather_collection_status": "success",
        "weather_error": "",
    }
    features, _ = compute_features(weather(), EVENT_TIME)
    row.update(features)
    return row


def negative_weather_row(identifier="negative-1"):
    row = negative(identifier)
    if identifier == "negative-b":
        row["longitude"] = "35.0"
    return build_negative_feature_row(row, weather())


def write_negatives(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=NEGATIVE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_negative_weather_semantics_are_identical_to_positive_semantics():
    expected, expected_status = compute_features(weather(), EVENT_TIME)
    row = negative_weather_row()
    assert {field: row[field] for field in FEATURE_FIELDS} == expected
    assert row["weather_collection_status"] == expected_status


def test_sample_timestamp_is_reference_and_post_event_value_is_excluded():
    row = negative_weather_row()
    assert row["temperature_1h_before"] == 167
    assert row["max_temperature_24h"] == 167
    assert row["max_temperature_3d"] == 167
    assert 9999 not in [row[field] for field in FEATURE_FIELDS]


def test_negative_fire_label_is_preserved_as_exact_zero():
    row = negative_weather_row()
    assert row["fire_label"] == 0
    assert row["negative_id"] == "negative-1"


def test_final_labels_and_sources_are_explicit():
    rows = combine_datasets([positive_weather_row()], [negative_weather_row()])
    by_type = {row["sample_type"]: row for row in rows}
    assert by_type["positive"]["fire_label"] == 1
    assert by_type["positive"]["label_source"] == "firms_candidate_with_official_month_support"
    assert by_type["negative"]["fire_label"] == 0
    assert by_type["negative"]["label_source"] == "firms_proxy_negative"


def test_unified_rows_have_identical_feature_columns():
    rows = combine_datasets([positive_weather_row()], [negative_weather_row()])
    assert all(tuple(field for field in UNIFIED_FIELDS if field in row) == UNIFIED_FIELDS for row in rows)
    assert all(set(FEATURE_FIELDS).issubset(row) for row in rows)
    assert ML_FEATURE_FIELDS == FEATURE_FIELDS


def test_firms_post_detection_variables_are_not_ml_features():
    assert not (set(ML_FEATURE_FIELDS) & FORBIDDEN_ML_FIELDS)
    assert "hotspot_count" not in UNIFIED_FIELDS
    assert "max_frp" not in UNIFIED_FIELDS
    assert "source_products" not in UNIFIED_FIELDS


def test_unified_dataset_is_deterministic():
    positive = positive_weather_row()
    first_negative = negative_weather_row("negative-a")
    second_negative = negative_weather_row("negative-b")
    first = combine_datasets([positive], [second_negative, first_negative])
    second = combine_datasets([positive], [first_negative, second_negative])
    assert first == second


def test_unified_validation_summary_reports_classes_and_no_duplicates():
    rows = combine_datasets([positive_weather_row()], [negative_weather_row()])
    summary = summarize_dataset(rows)
    assert summary["positive_rows"] == 1
    assert summary["negative_rows"] == 1
    assert summary["class_ratio_positive_to_negative"] == "1:1"
    assert summary["duplicate_sample_ids"] == 0
    assert summary["duplicate_timestamp_coordinates"] == 0
    assert set(summary["null_counts"]) == set(FEATURE_FIELDS)


class FakeClient:
    endpoint = "https://example.test/v1/archive"

    def __init__(self):
        self.calls = []

    def fetch(self, latitude, longitude, event_time):
        self.calls.append((latitude, longitude, event_time))
        return weather()


def test_negative_weather_checkpoint_resume(tmp_path):
    input_path = tmp_path / "negatives.csv"
    output_path = tmp_path / "weather.csv"
    checkpoint = tmp_path / "checkpoint"
    write_negatives(input_path, [negative()])
    first_client = FakeClient()
    first = build_negative_weather_features(
        input_path=input_path,
        output_path=output_path,
        checkpoint_path=checkpoint,
        client=first_client,
        progress_logger=lambda _: None,
        request_pause_seconds=0,
    )
    second_client = FakeClient()
    second = build_negative_weather_features(
        input_path=input_path,
        output_path=output_path,
        checkpoint_path=checkpoint,
        client=second_client,
        progress_logger=lambda _: None,
        request_pause_seconds=0,
    )
    assert len(first_client.calls) == 1
    assert first_client.calls[0][2] == EVENT_TIME
    assert second_client.calls == []
    assert first == second
