"""Parsing checks for the historical hydrograph CSV cache."""

from __future__ import annotations

import csv
from datetime import datetime, timezone

import pytest

from ecoguard.collection.flood.historical_observations import (
    EXPECTED_FIELDS,
    HistoricalHydrographError,
    _batches,
    inspect_historical_hydrograph_file,
    iter_historical_hydrograph_rows,
    parse_historical_hydrograph_row,
)


def _row(**overrides):
    row = {
        "זיהוי תחנה": "1102",
        "שם תחנה": "בצת-כביש 4",
        "שם תחנה באנגלית": "BEZET- ROAD 4",
        "שנה הידרולוגית": "2017/2018",
        "זמן מדידת ספיקה": "24/01/2018 09:17:00",
        "רום המים (מ')": "9.97",
        "ספיקה (מ''ק/שנייה)": "0.048",
        "סוג נתון": "מדודים",
        "סוג זרימה": "גאות",
        "סוג רשומה": "נקודה פנימית",
    }
    row.update(overrides)
    return row


def _write_csv(path, rows, *, fields=EXPECTED_FIELDS):
    with path.open("w", encoding="cp1255", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_parses_cp1255_measurements_and_converts_local_time_to_utc(tmp_path):
    path = tmp_path / "hydrograph.csv"
    _write_csv(path, [_row()])

    rows = list(iter_historical_hydrograph_rows(path))

    assert len(rows) == 1
    assert rows[0]["source_row_number"] == 2
    assert rows[0]["historical_station_id"] == 1102
    assert rows[0]["observed_at"] == datetime(
        2018, 1, 24, 7, 17, tzinfo=timezone.utc
    )
    assert rows[0]["water_height_m"] == 9.97
    assert rows[0]["discharge_m3s"] == 0.048
    assert rows[0]["is_sewage"] is False


def test_marks_sewage_for_storage_but_not_as_normal_flow():
    parsed = parse_historical_hydrograph_row(
        _row(**{"סוג זרימה": "ביוב"}),
        source_row_number=7,
    )

    assert parsed["is_sewage"] is True
    assert parsed["flow_type"] == "ביוב"


def test_accepts_one_missing_metric_without_fabricating_a_value():
    parsed = parse_historical_hydrograph_row(
        _row(**{"רום המים (מ')": ""}),
        source_row_number=2,
    )

    assert parsed["water_height_m"] is None
    assert parsed["discharge_m3s"] == 0.048


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"רום המים (מ')": "", "ספיקה (מ''ק/שנייה)": ""}, "no measurement"),
        ({"ספיקה (מ''ק/שנייה)": "-0.1"}, "invalid discharge"),
        ({"שנה הידרולוגית": "2017/2019"}, "hydrological year"),
        ({"זמן מדידת ספיקה": "2018-01-24"}, "observation timestamp"),
    ],
)
def test_rejects_rows_that_cannot_be_interpreted_safely(overrides, message):
    with pytest.raises(HistoricalHydrographError, match=message):
        parse_historical_hydrograph_row(
            _row(**overrides),
            source_row_number=2,
        )


def test_rejects_an_unexpected_header(tmp_path):
    path = tmp_path / "hydrograph.csv"
    _write_csv(path, [{"זיהוי תחנה": "1102"}], fields=("זיהוי תחנה",))

    with pytest.raises(HistoricalHydrographError, match="unexpected header"):
        list(iter_historical_hydrograph_rows(path))


def test_inspection_produces_content_identity_and_source_coverage(tmp_path):
    path = tmp_path / "hydrograph.csv"
    _write_csv(
        path,
        [
            _row(),
            _row(
                **{
                    "זיהוי תחנה": "2105",
                    "זמן מדידת ספיקה": "03/10/2019 11:11:00",
                    "שנה הידרולוגית": "2019/2020",
                }
            ),
        ],
    )

    source = inspect_historical_hydrograph_file(path)

    assert source.source_name == "hydrograph.csv"
    assert source.row_count == 2
    assert source.station_ids == frozenset({1102, 2105})
    assert len(source.checksum) == 64
    assert source.first_observed_at < source.last_observed_at


def test_batches_keep_order_and_do_not_drop_a_partial_tail():
    rows = [{"value": value} for value in range(5)]

    batches = list(_batches(rows, size=2))

    assert [[row["value"] for row in batch] for batch in batches] == [
        [0, 1],
        [2, 3],
        [4],
    ]
