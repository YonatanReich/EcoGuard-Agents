"""Tests for the offline Hebrew fire-location extractor."""

import sqlite3
from pathlib import Path

import pytest

import agents.hebrew_fire_location_extractor as extractor


@pytest.fixture()
def location_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache_path = tmp_path / "locations.sqlite3"
    connection = sqlite3.connect(cache_path)
    connection.executescript(extractor.CACHE_SCHEMA_SQL)

    localities = (
        (8300, "ראשון לציון"),
        (8500, "רמלה"),
        (7900, "פתח תקווה"),
        (4000, "חיפה"),
        (3760, "סעיר"),
        (1286, "שני"),
        (3574, "בית אל"),
        (95, "בית אלפא"),
    )
    for code, name in localities:
        normalized = extractor.normalize_location_name(name)
        connection.execute(
            "INSERT INTO localities VALUES (?, ?, ?)",
            (code, name, normalized),
        )
        connection.execute(
            "INSERT INTO locality_names VALUES (?, ?, ?, 'official')",
            (code, name, normalized),
        )

    streets = (
        (8300, 101, "התותחנים"),
        (8500, 102, "משה לוי"),
        (7900, 103, "הרצל"),
        (7900, 104, "זאב אורלוב"),
        (4000, 105, "התותחנים"),
    )
    for city_code, street_code, name in streets:
        normalized = extractor.normalize_location_name(name)
        connection.execute(
            "INSERT INTO streets VALUES (?, ?, ?, ?)",
            (city_code, street_code, name, normalized),
        )
        connection.execute(
            "INSERT INTO street_names VALUES (?, ?, ?, ?, 'official')",
            (city_code, street_code, name, normalized),
        )

    connection.execute(
        "INSERT INTO street_names VALUES (?, ?, ?, ?, 'synonym')",
        (7900, 104, "אורלוב", extractor.normalize_location_name("אורלוב")),
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(extractor, "CACHE_PATH", cache_path)
    return cache_path


def test_dispatch_style_validates_street_in_city(location_cache: Path):
    result = extractor.extract_fire_location("ראשון לציון התותחנים שריפה")

    assert result["city"] == "ראשון לציון"
    assert result["street"] == "התותחנים"
    assert result["location_text"] == "ראשון לציון התותחנים"
    assert result["confidence"] == 0.88


def test_dispatch_style_supports_multiword_street(location_cache: Path):
    result = extractor.extract_fire_location("רמלה משה לוי שריפה במבנה")

    assert result["city"] == "רמלה"
    assert result["street"] == "משה לוי"


def test_longest_locality_name_wins(location_cache: Path):
    result = extractor.extract_fire_location("שריפה בבית אלפא")

    assert result["city"] == "בית אלפא"


def test_attached_prefix_matches_locality(location_cache: Path):
    result = extractor.extract_fire_location("משאית עולה באש בפתח תקווה")

    assert result["city"] == "פתח תקווה"
    assert result["street"] is None
    assert result["location_text"] == "בפתח תקווה"


def test_explicit_street_is_validated_inside_city(location_cache: Path):
    result = extractor.extract_fire_location("שריפה ברחוב הרצל בפתח תקווה")

    assert result["city"] == "פתח תקווה"
    assert result["street"] == "הרצל"
    assert result["location_text"] == "ברחוב הרצל בפתח תקווה"


def test_real_street_in_wrong_city_is_not_returned(location_cache: Path):
    result = extractor.extract_fire_location("שריפה ברחוב התותחנים ברמלה")

    assert result["city"] == "רמלה"
    assert result["street"] is None


def test_street_synonym_returns_canonical_name(location_cache: Path):
    result = extractor.extract_fire_location("שריפה ברחוב אורלוב בפתח תקווה")

    assert result["street"] == "זאב אורלוב"


def test_explicit_neighborhood_wording_is_preserved(location_cache: Path):
    result = extractor.extract_fire_location("שריפה בשכונת זיו בחיפה")

    assert result["city"] == "חיפה"
    assert result["neighborhood"] == "זיו"
    assert result["location_text"] == "בשכונת זיו בחיפה"


def test_proximity_requires_official_locality(location_cache: Path):
    result = extractor.extract_fire_location("שריפת מבנה בסמוך לסעיר")

    assert result["city"] == "סעיר"
    assert result["location_text"] == "בסמוך לסעיר"


def test_explicit_proximity_outranks_ordinary_locality_word(
    location_cache: Path,
):
    text = """שוטרי מחוז ש"י חוקרים אירוע סמוך לסעיר.
מהמקום פונו שני פצועי ירי לבית החולים.
התקבל דיווח על שריפת מבנה בסמוך."""

    result = extractor.extract_fire_location(text)

    assert result["city"] == "סעיר"
    assert result["location_text"] == "סמוך לסעיר"


def test_specific_neighborhood_outranks_generic_description(
    location_cache: Path,
):
    text = """שריפה בשטח פתוח שנבלמה בתוך שכונת מגורים בחיפה.
עשן שעלה מחורשה בשכונת זיו בחיפה."""

    result = extractor.extract_fire_location(text)

    assert result["city"] == "חיפה"
    assert result["neighborhood"] == "זיו"
    assert result["location_text"] == "בשכונת זיו בחיפה"


def test_unknown_locality_is_not_invented(location_cache: Path):
    result = extractor.extract_fire_location("שריפה בסמוך למקוםלאקיים")

    assert result == extractor._empty_result()


def test_weapons_phrase_does_not_match_partial_locality(location_cache: Path):
    result = extractor.extract_fire_location("החשוד פתח באש")

    assert result == extractor._empty_result()


def test_person_name_is_not_an_unvalidated_street(location_cache: Path):
    result = extractor.extract_fire_location("רמלה ישראל ישראלי שריפה")

    assert result["city"] == "רמלה"
    assert result["street"] is None


@pytest.mark.parametrize("text", [None, "", "  \n\t"])
def test_empty_input_returns_empty_result(location_cache: Path, text: str | None):
    assert extractor.extract_fire_location(text) == extractor._empty_result()


def test_missing_cache_returns_empty_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(extractor, "CACHE_PATH", tmp_path / "missing.sqlite3")

    assert extractor.extract_fire_location("שריפה בחיפה") == extractor._empty_result()


@pytest.mark.skipif(not extractor.CACHE_PATH.is_file(), reason="official cache absent")
def test_optional_official_cache_integration():
    result = extractor.extract_fire_location("משאית עולה באש בפתח תקווה")

    assert result["city"] == "פתח תקווה"
