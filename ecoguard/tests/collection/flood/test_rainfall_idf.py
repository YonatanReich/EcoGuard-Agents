"""Validation tests for the IMS rainfall IDF import."""

from __future__ import annotations

import csv
from decimal import Decimal, ROUND_HALF_UP

import pytest

from ecoguard.collection.flood.rainfall_idf import (
    EXPECTED_COLUMNS,
    EXPECTED_DURATIONS,
    EXPECTED_MEASURE_TYPES,
    EXPECTED_PROBABILITIES,
    IDF_STATION_SOURCE_IDS,
    RainfallIdfImportError,
    parse_rainfall_idf_csv,
)


def _complete_rows(station_name: str = "תחנה לדוגמה") -> list[list[object]]:
    rows: list[list[object]] = []
    for measure_type in sorted(EXPECTED_MEASURE_TYPES):
        for probability in sorted(EXPECTED_PROBABILITIES, reverse=True):
            return_period = (Decimal("100") / probability).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
            probability_label = f"{probability}%"
            for duration in sorted(EXPECTED_DURATIONS):
                rows.append(
                    [
                        station_name,
                        measure_type,
                        30,
                        duration,
                        probability_label,
                        return_period,
                        10.0,
                        9.0,
                        11.0,
                    ]
                )
    return rows


def _write_csv(path, rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(EXPECTED_COLUMNS)
        writer.writerows(rows)


def test_station_mapping_is_complete_and_keeps_beer_sheva_override():
    assert len(IDF_STATION_SOURCE_IDS) == 63
    assert len(set(IDF_STATION_SOURCE_IDS.values())) == 63
    assert IDF_STATION_SOURCE_IDS["באר שבע"] == 411


def test_parses_one_complete_station_matrix(tmp_path):
    source = tmp_path / "idf.csv"
    _write_csv(source, _complete_rows())

    rows = parse_rainfall_idf_csv(
        source, station_source_ids={"תחנה לדוגמה": 700}
    )

    assert len(rows) == 2 * 14 * 11
    assert {row.source_station_id for row in rows} == {700}
    assert {row.number_of_years for row in rows} == {30}
    assert {row.match_method for row in rows} == {"official_name_exact"}


def test_rejects_an_incomplete_station_matrix(tmp_path):
    source = tmp_path / "idf.csv"
    _write_csv(source, _complete_rows()[:-1])

    with pytest.raises(RainfallIdfImportError, match="complete IDF matrix"):
        parse_rainfall_idf_csv(
            source, station_source_ids={"תחנה לדוגמה": 700}
        )


def test_rejects_duplicate_values(tmp_path):
    source = tmp_path / "idf.csv"
    rows = _complete_rows()
    _write_csv(source, rows + [rows[0]])

    with pytest.raises(RainfallIdfImportError, match="duplicate IDF value"):
        parse_rainfall_idf_csv(
            source, station_source_ids={"תחנה לדוגמה": 700}
        )


def test_rejects_value_outside_confidence_bounds(tmp_path):
    source = tmp_path / "idf.csv"
    rows = _complete_rows()
    rows[0][-3:] = [8.0, 9.0, 11.0]
    _write_csv(source, rows)

    with pytest.raises(RainfallIdfImportError, match="lower <= value <= upper"):
        parse_rainfall_idf_csv(
            source, station_source_ids={"תחנה לדוגמה": 700}
        )


def test_marks_beer_sheva_as_manual_override(tmp_path):
    source = tmp_path / "idf.csv"
    _write_csv(source, _complete_rows("באר שבע"))

    rows = parse_rainfall_idf_csv(
        source, station_source_ids={"באר שבע": 411}
    )

    assert {row.match_method for row in rows} == {"manual_override"}
