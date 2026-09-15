"""Offline, deterministic location extraction for Hebrew fire reports."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path


CACHE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "generated"
    / "israel_locations.sqlite3"
)

CACHE_SCHEMA_SQL = """
CREATE TABLE localities (
    locality_code INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL
);
CREATE TABLE locality_names (
    locality_code INTEGER NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    name_kind TEXT NOT NULL,
    PRIMARY KEY (locality_code, normalized_name),
    FOREIGN KEY (locality_code) REFERENCES localities(locality_code)
);
CREATE TABLE streets (
    locality_code INTEGER NOT NULL,
    street_code INTEGER NOT NULL,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    PRIMARY KEY (locality_code, street_code),
    FOREIGN KEY (locality_code) REFERENCES localities(locality_code)
);
CREATE TABLE street_names (
    locality_code INTEGER NOT NULL,
    official_street_code INTEGER NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    name_kind TEXT NOT NULL,
    PRIMARY KEY (locality_code, official_street_code, normalized_name),
    FOREIGN KEY (locality_code, official_street_code)
        REFERENCES streets(locality_code, street_code)
);
CREATE INDEX locality_names_by_normalized
    ON locality_names(normalized_name);
CREATE INDEX street_names_by_locality_and_normalized
    ON street_names(locality_code, normalized_name);
"""

_NIQQUD_PATTERN = re.compile(
    "[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]"
)
_TOKEN_PATTERN = re.compile(r"[^\W_]+(?:[׳'״\"]+[^\W_]+)*", re.UNICODE)
_HEBREW_PREFIXES = frozenset("בלמהוכ")
_STRONG_LOCATION_PREFIXES = frozenset("בל")
_PROXIMITY_MARKERS = frozenset(("בסמוך", "סמוך", "ליד", "בקרבת"))
_STREET_MARKERS = frozenset(("רחוב", "ברחוב"))
_NEIGHBORHOOD_MARKERS = frozenset(("שכונת", "בשכונת"))
_GENERIC_NEIGHBORHOOD_TERMS = frozenset(("מגורים",))
_FIRE_MARKERS = frozenset(
    ("שריפה", "שרפה", "שריפת", "בוער", "בוערת", "בוערים", "להבות")
)


@dataclass(frozen=True)
class _Token:
    normalized: str
    start: int
    end: int


@dataclass(frozen=True)
class _LocalityMatch:
    code: int
    name: str
    start_token: int
    end_token: int
    prefixed: bool


def normalize_location_name(value: str) -> str:
    """Create a conservative Hebrew lookup key."""
    value = _NIQQUD_PATTERN.sub("", value)
    value = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in value
    )
    return " ".join(value.casefold().split())


def _empty_result() -> dict:
    return {
        "location_text": None,
        "city": None,
        "street": None,
        "neighborhood": None,
        "latitude": None,
        "longitude": None,
        "confidence": 0.0,
    }


def _tokenize(text: str) -> list[_Token]:
    tokens = []
    for match in _TOKEN_PATTERN.finditer(text):
        normalized = normalize_location_name(match.group())
        if normalized:
            tokens.append(_Token(normalized, match.start(), match.end()))
    return tokens


def _open_cache() -> sqlite3.Connection | None:
    if not CACHE_PATH.is_file():
        return None
    try:
        connection = sqlite3.connect(
            f"{CACHE_PATH.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("SELECT 1 FROM localities LIMIT 1").fetchone()
        return connection
    except (OSError, sqlite3.Error):
        return None


def _locality_candidates(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT locality_names.locality_code,
               localities.canonical_name,
               locality_names.normalized_name
        FROM locality_names
        JOIN localities USING (locality_code)
        ORDER BY length(locality_names.normalized_name) DESC
        """
    ).fetchall()


def _match_locality(
    tokens: list[_Token],
    connection: sqlite3.Connection,
) -> _LocalityMatch | None:
    matches = []
    for row in _locality_candidates(connection):
        name_tokens = row["normalized_name"].split()
        width = len(name_tokens)
        for start in range(0, len(tokens) - width + 1):
            candidate = [token.normalized for token in tokens[start : start + width]]
            exact = candidate == name_tokens
            prefixed = (
                len(candidate[0]) > 1
                and candidate[0][0] in _HEBREW_PREFIXES
                and [candidate[0][1:], *candidate[1:]] == name_tokens
            )
            if exact or prefixed:
                matches.append(
                    (
                        width,
                        -start,
                        _LocalityMatch(
                            row["locality_code"],
                            row["canonical_name"],
                            start,
                            start + width,
                            prefixed,
                        ),
                    )
                )
    if not matches:
        return None

    def evidence_score(match: _LocalityMatch) -> int:
        previous = (
            tokens[match.start_token - 1].normalized
            if match.start_token > 0
            else None
        )
        if previous in _PROXIMITY_MARKERS:
            return 100

        for marker_index in range(
            max(0, match.start_token - 4),
            match.start_token,
        ):
            marker = tokens[marker_index].normalized
            words_between = match.start_token - marker_index - 1
            if marker in _NEIGHBORHOOD_MARKERS and 1 <= words_between <= 3:
                neighborhood = " ".join(
                    token.normalized
                    for token in tokens[marker_index + 1 : match.start_token]
                )
                if neighborhood not in _GENERIC_NEIGHBORHOOD_TERMS:
                    return 95
            if marker in _STREET_MARKERS and 1 <= words_between <= 5:
                return 90

        if match.start_token == 0:
            return 85
        first_token = tokens[match.start_token].normalized
        if match.prefixed and first_token[0] in _STRONG_LOCATION_PREFIXES:
            return 80
        return 0

    ranked_matches = [
        (evidence_score(match), width, position, match)
        for width, position, match in matches
    ]
    best = max(ranked_matches, key=lambda item: (item[0], item[1], item[2]))
    return best[3] if best[0] > 0 else None


def _street_names(
    connection: sqlite3.Connection,
    locality_code: int,
) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT street_names.normalized_name, streets.canonical_name
        FROM street_names
        JOIN streets
          ON streets.locality_code = street_names.locality_code
         AND streets.street_code = street_names.official_street_code
        WHERE street_names.locality_code = ?
        """,
        (locality_code,),
    ).fetchall()
    return {row["normalized_name"]: row["canonical_name"] for row in rows}


def _validated_street(
    tokens: list[_Token],
    start: int,
    end: int,
    names: dict[str, str],
) -> tuple[str, int, int] | None:
    if start >= end:
        return None
    for candidate_end in range(end, start, -1):
        value = " ".join(token.normalized for token in tokens[start:candidate_end])
        canonical = names.get(value)
        if canonical:
            return canonical, start, candidate_end
    return None


def _original_span(text: str, tokens: list[_Token], start: int, end: int) -> str:
    return text[tokens[start].start : tokens[end - 1].end].strip()


def extract_fire_location(text: str | None) -> dict:
    """Extract a cache-validated location without networking or geocoding."""
    if text is None or not text.strip():
        return _empty_result()

    connection = _open_cache()
    if connection is None:
        return _empty_result()

    try:
        tokens = _tokenize(text)
        locality = _match_locality(tokens, connection)
        if locality is None:
            return _empty_result()

        result = _empty_result()
        result["city"] = locality.name
        result["location_text"] = _original_span(
            text,
            tokens,
            locality.start_token,
            locality.end_token,
        )
        result["confidence"] = 0.85

        street_names = _street_names(connection, locality.code)

        for marker_index, token in enumerate(tokens):
            if token.normalized not in _STREET_MARKERS:
                continue
            street_start = marker_index + 1
            street_end = (
                locality.start_token
                if locality.start_token > street_start
                else min(len(tokens), street_start + 5)
            )
            street = _validated_street(
                tokens,
                street_start,
                street_end,
                street_names,
            )
            if street:
                result["street"] = street[0]
                span_start = min(marker_index, locality.start_token)
                span_end = max(street[2], locality.end_token)
                result["location_text"] = _original_span(
                    text, tokens, span_start, span_end
                )
                result["confidence"] = 0.95
                return result

        if locality.start_token == 0:
            fire_index = next(
                (
                    index
                    for index in range(locality.end_token, len(tokens))
                    if tokens[index].normalized in _FIRE_MARKERS
                ),
                None,
            )
            if fire_index is not None:
                street = _validated_street(
                    tokens,
                    locality.end_token,
                    fire_index,
                    street_names,
                )
                if street and street[2] == fire_index:
                    result["street"] = street[0]
                    result["location_text"] = _original_span(
                        text, tokens, locality.start_token, street[2]
                    )
                    result["confidence"] = 0.88
                    return result

        for marker_index in range(locality.start_token - 1, -1, -1):
            token = tokens[marker_index]
            if token.normalized not in _NEIGHBORHOOD_MARKERS:
                continue
            name_start = marker_index + 1
            name_width = locality.start_token - name_start
            if not 1 <= name_width <= 3:
                continue
            neighborhood = " ".join(
                item.normalized
                for item in tokens[name_start : locality.start_token]
            )
            if neighborhood in _GENERIC_NEIGHBORHOOD_TERMS:
                continue
            result["neighborhood"] = _original_span(
                text, tokens, name_start, locality.start_token
            )
            result["location_text"] = _original_span(
                text, tokens, marker_index, locality.end_token
            )
            result["confidence"] = 0.90
            return result

        if locality.start_token > 0:
            previous = tokens[locality.start_token - 1].normalized
            if previous in _PROXIMITY_MARKERS:
                result["location_text"] = _original_span(
                    text,
                    tokens,
                    locality.start_token - 1,
                    locality.end_token,
                )

        return result
    except sqlite3.Error:
        return _empty_result()
    finally:
        connection.close()
