from datetime import datetime, timezone

from ecoguard.research.datasets.build_strong_historical_wildfire_ground_truth import (
    confidence_tier, match_firms, normalize_external_events,
)


def firms(identifier="f1", timestamp="2024-06-01T10:00:00Z", latitude=32.0, longitude=35.0):
    start = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return {"candidate_id": identifier, "_start": start, "_end": start, "_latitude": latitude, "_longitude": longitude}


def event(identifier="official-1", **changes):
    row = {"event_timestamp_start": "2024-06-01T10:15:00Z", "event_timestamp_end": "", "latitude": "32.001", "longitude": "35.001", "location_name": "Official reserve", "event_type": "wildfire", "source_name": "nature_parks", "source_url_or_identifier": identifier, "source_authority_level": "official_land_manager", "timestamp_precision": "minute", "location_precision": "coordinates", "open_area_indicator": "true", "notes": "source text retained"}
    row.update(changes); return row


def test_strong_and_probable_tier_rules_do_not_fabricate_precision():
    exact = event(); matched = match_firms(exact, [firms()])
    assert confidence_tier(exact, matched) == ("strong_event_support", 0.95)
    date_only = event(event_timestamp_start="2024-06-01", timestamp_precision="date", location_precision="area_name")
    assert confidence_tier(date_only, match_firms(date_only, [firms()])) == ("multi_source_probable_fire", 0.80)
    no_coordinates = event(latitude="", longitude="", location_precision="area_name")
    assert confidence_tier(no_coordinates, match_firms(no_coordinates, [firms()])) == (None, 0.0)


def test_firms_matching_respects_space_and_time_and_reports_ambiguity():
    source = event()
    result = match_firms(source, [firms("near"), firms("far", latitude=33.0), firms("late", timestamp="2024-07-01T10:00:00Z")])
    assert result["status"] == "matched" and result["selected"][2]["candidate_id"] == "near"
    ambiguous = match_firms(source, [firms("a"), firms("b", latitude=32.002)])
    assert ambiguous["status"] == "ambiguous_multiple" and len(ambiguous["matches"]) == 2


def test_normalization_is_deterministic_deduplicates_and_preserves_provenance():
    rows = [event("b"), event("a"), event("a")]
    first, rejected = normalize_external_events(rows, [firms()], {"32.001000,35.001000": "grassland"})
    second, _ = normalize_external_events(reversed(rows), [firms()], {"32.001000,35.001000": "grassland"})
    assert first == second
    assert len(first) == 2 and rejected["duplicate_or_missing_source_identity"] == 1
    assert first[0]["source_url_or_identifier"] == "a"
    assert first[0]["land_cover_context"] == "grassland"
    assert first[0]["notes"] == "source text retained"
    assert first[0]["official_event_count"] == ""


def test_year_range_and_weak_sources_are_rejected():
    rows = [event("old", event_timestamp_start="2022-06-01T10:00:00Z"), event("weak", source_authority_level="social_media")]
    output, rejected = normalize_external_events(rows, [firms()], {})
    assert output == []
    assert rejected == {"outside_year_range": 1, "insufficient_event_level_support": 1}


def test_date_precision_matches_whole_day_without_inventing_output_time():
    source = event(event_timestamp_start="2024-06-01", timestamp_precision="date", location_precision="area_name")
    output, _ = normalize_external_events([source], [firms(timestamp="2024-06-01T23:00:00Z")], {})
    assert output[0]["event_timestamp_start"] == "2024-06-01"
    assert output[0]["timestamp_precision"] == "date"
