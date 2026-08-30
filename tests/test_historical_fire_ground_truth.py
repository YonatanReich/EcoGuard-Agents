from scripts.build_historical_fire_ground_truth import (
    deduplicate_records,
    normalize_column_name,
    normalize_records,
    parse_event_count,
)


HEBREW_ROW = {
    "\ufeffשנה": "2024",
    "EventMonth": "10",
    "מחוז": "מרכז",
    "תחום": "שריפות",
    "מתאר": "שטחים פתוחים",
    "תרחיש": "שריפת צמחייה",
    "מיקום": "רמלה",
    "SettlementLamasCode": "8500",
    "מספר אירועים": "7",
}


def normalize(rows):
    return normalize_records(
        rows,
        source_resource="resource-1",
        source_updated_at="2025-01-01T00:00:00",
    )


def test_column_name_normalization_handles_bom_spacing_and_case():
    assert normalize_column_name("\ufeff Event_Type ") == "eventtype"
    assert normalize_column_name("מספר אירועים") == "מספראירועים"


def test_hebrew_fields_are_normalized_and_aggregate_is_not_expanded():
    records, malformed = normalize([HEBREW_ROW])
    assert malformed == 0
    assert len(records) == 1
    assert records[0] == {
        "year": 2024,
        "month": 10,
        "district": "מרכז",
        "event_domain": "שריפה",
        "event_type": "שטחים פתוחים",
        "scenario": "שריפת צמחייה",
        "settlement": "רמלה",
        "settlement_lamas_code": "8500",
        "event_count": 7,
        "source": "israel_fire_and_rescue",
        "source_resource": "resource-1",
        "source_updated_at": "2025-01-01T00:00:00",
    }


def test_non_fire_domain_is_filtered():
    row = {**HEBREW_ROW, "תחום": "חילוץ"}
    assert normalize([row])[0] == []


def test_non_open_area_type_is_filtered():
    row = {**HEBREW_ROW, "מתאר": "מבנה"}
    assert normalize([row])[0] == []


def test_english_column_and_value_variations_are_supported():
    row = {
        "Year": "2023",
        "Month": "2",
        "District": "North",
        "Domain": "Fire",
        "Event Type": "Open Areas",
        "Scenario": "Vegetation",
        "Settlement": "Example",
        "Settlement Code": "12",
        "Event Count": "1,234",
    }
    records, _ = normalize([row])
    assert records[0]["event_count"] == 1234


def test_event_count_parsing():
    assert parse_event_count(" 1,234 ") == 1234
    assert parse_event_count("7.0") == 7
    assert parse_event_count(0) == 0
    assert parse_event_count("1.5") is None
    assert parse_event_count("invalid") is None
    assert parse_event_count(None) is None


def test_exact_duplicates_across_resources_are_removed():
    records, _ = normalize([HEBREW_ROW])
    older = records[0]
    newer = {
        **older,
        "source_resource": "resource-2",
        "source_updated_at": "2025-02-01T00:00:00",
    }
    result = deduplicate_records([older, newer])
    assert len(result) == 1
    assert result[0]["source_resource"] == "resource-2"


def test_missing_optional_fields_are_empty_without_invention():
    row = {
        "Year": 2026,
        "Month": 1,
        "Domain": "fires",
        "EventType": "open area",
        "Count": 2,
    }
    records, malformed = normalize([row])
    assert malformed == 0
    assert records[0]["district"] == ""
    assert records[0]["scenario"] == ""
    assert records[0]["settlement"] == ""
    assert records[0]["settlement_lamas_code"] == ""


def test_malformed_required_values_are_skipped_safely():
    rows = [
        {**HEBREW_ROW, "מספר אירועים": "bad"},
        {**HEBREW_ROW, "EventMonth": "13"},
    ]
    records, malformed = normalize(rows)
    assert records == []
    assert malformed == 2


def test_out_of_scope_year_is_filtered():
    records, malformed = normalize([{**HEBREW_ROW, "\ufeffשנה": "2022"}])
    assert records == []
    assert malformed == 0
