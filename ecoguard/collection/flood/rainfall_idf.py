"""Validate and import IMS rainfall IDF curves.

The IMS dashboard does not expose station identifiers.  Its 63 station names
were reconciled once against the existing ``rain_stations`` catalog.  Keeping
that mapping explicit makes future imports deterministic: no fuzzy match can
silently attach a curve to a different station.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Mapping, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session as OrmSession

from ecoguard.database.engine import Session


SOURCE_DATASET = "ims_rainfall_dashboard_v9_may_2026"
EXPECTED_COLUMNS = (
    "station",
    "measure_type",
    "number_of_years",
    "duration_minutes",
    "probability",
    "return_period_years",
    "value",
    "lower",
    "upper",
)
EXPECTED_MEASURE_TYPES = frozenset({"amount", "intensity"})
EXPECTED_DURATIONS = frozenset(
    {10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 480, 720, 1440, 2880}
)
EXPECTED_PROBABILITIES = frozenset(
    {
        Decimal("50"),
        Decimal("25"),
        Decimal("20"),
        Decimal("15"),
        Decimal("10"),
        Decimal("5"),
        Decimal("4"),
        Decimal("3"),
        Decimal("2"),
        Decimal("1"),
        Decimal("0.5"),
    }
)

# source_station_id values belong to the existing Water Authority/Envista rain
# catalog. Beer Sheva is the one deliberate non-exact name match: the dashboard
# calls the long historical series "באר שבע", while the live catalog calls the
# matched station "באר שבע, אוניברסיטת בן גוריון" (Beer Sheva BGU).
IDF_STATION_SOURCE_IDS: dict[str, int] = {
    "בית דגן": 54,
    "ירושלים, גבעת רם": 22,
    "צומת הנגב": 112,
    "דורות": 79,
    "סדום": 65,
    "הר חרשה": 24,
    "אפק": 78,
    "אשקלון, נמל": 208,
    "תל יוסף": 380,
    "מצפה רמון": 379,
    "אשחר": 205,
    "עפולה, ניר העמק": 16,
    "כפר גלעדי": 241,
    "אבני איתן": 2,
    "אריאל": 21,
    "דפנה": 499,
    "איילת השחר": 353,
    "צפת, הר-כנען": 62,
    "גלגל": 30,
    "נגבה": 82,
    "ירושלים, מרכז": 23,
    "מרום גולן, פיכמן": 10,
    "אילת": 64,
    "עין כרמל": 44,
    "ניצן": 274,
    "להב": 350,
    "חוות עדן": 206,
    "חוות הבשור": 58,
    "איתמר": 90,
    "אילון": 73,
    "יבנאל": 11,
    "חפץ חיים": 121,
    "באר שבע": 411,
    "בית ציידא": 6,
    "קרני שומרון": 20,
    "פארן": 207,
    "דיר חנא": 99,
    "שבי ציון": 343,
    "מעלה גלבוע": 224,
    "עמיעד": 123,
    "תבור, כדורי": 13,
    "עין השופט": 67,
    "אשדוד, נמל": 124,
    "חיפה, אוניברסיטה": 42,
    "ראש צורים": 77,
    "שני": 28,
    "צובה": 188,
    "ערד": 29,
    "נווה יער": 186,
    "תל אביב, חוף": 178,
    "שדה בוקר": 98,
    "צמח": 8,
    "עין החורש": 107,
    "כפר בלום": 202,
    "מצוקי דרגות": 210,
    "גת": 236,
    "בית ג'מל": 75,
    "זכרון יעקב": 45,
    "שדה אליהו": 366,
    "קבוצת יבנה": 74,
    "גלעד": 263,
    'נתיב הל"ה': 25,
    "חיפה, בתי זיקוק": 41,
}


class RainfallIdfImportError(ValueError):
    """The supplied IDF dataset is incomplete, inconsistent, or unlinked."""


@dataclass(frozen=True)
class RainfallIdfRow:
    source_station_name_he: str
    source_station_id: int
    measure_type: str
    number_of_years: int
    duration_minutes: int
    probability_percent: Decimal
    return_period_years: Decimal
    estimate: float
    lower_bound: float
    upper_bound: float
    match_method: str


def _positive_int(value: str, label: str, row_number: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise RainfallIdfImportError(
            f"row {row_number}: {label} must be an integer"
        ) from error
    if result <= 0:
        raise RainfallIdfImportError(f"row {row_number}: {label} must be positive")
    return result


def _decimal(value: str, label: str, row_number: int) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError) as error:
        raise RainfallIdfImportError(
            f"row {row_number}: {label} must be numeric"
        ) from error
    if not result.is_finite():
        raise RainfallIdfImportError(f"row {row_number}: {label} must be finite")
    return result


def _nonnegative_float(value: str, label: str, row_number: int) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise RainfallIdfImportError(
            f"row {row_number}: {label} must be numeric"
        ) from error
    if not math.isfinite(result) or result < 0:
        raise RainfallIdfImportError(
            f"row {row_number}: {label} must be finite and nonnegative"
        )
    return result


def _parse_probability(value: str, row_number: int) -> Decimal:
    if not value or not value.endswith("%"):
        raise RainfallIdfImportError(
            f"row {row_number}: probability must end with %"
        )
    probability = _decimal(value[:-1], "probability", row_number)
    if probability not in EXPECTED_PROBABILITIES:
        raise RainfallIdfImportError(
            f"row {row_number}: unsupported probability {value}"
        )
    return probability


def _parse_row(
    raw: Mapping[str, str],
    row_number: int,
    station_source_ids: Mapping[str, int],
) -> RainfallIdfRow:
    station_name = (raw.get("station") or "").strip()
    if station_name not in station_source_ids:
        raise RainfallIdfImportError(
            f"row {row_number}: unmapped IDF station {station_name!r}"
        )

    measure_type = (raw.get("measure_type") or "").strip()
    if measure_type not in EXPECTED_MEASURE_TYPES:
        raise RainfallIdfImportError(
            f"row {row_number}: unsupported measure_type {measure_type!r}"
        )

    number_of_years = _positive_int(
        raw.get("number_of_years", ""), "number_of_years", row_number
    )
    duration = _positive_int(
        raw.get("duration_minutes", ""), "duration_minutes", row_number
    )
    if duration not in EXPECTED_DURATIONS:
        raise RainfallIdfImportError(
            f"row {row_number}: unsupported duration {duration}"
        )

    probability = _parse_probability(raw.get("probability", ""), row_number)
    return_period = _decimal(
        raw.get("return_period_years", ""), "return_period_years", row_number
    )
    expected_return_period = (Decimal("100") / probability).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    if return_period != expected_return_period:
        raise RainfallIdfImportError(
            f"row {row_number}: return period {return_period} does not match "
            f"probability {probability}%"
        )

    estimate = _nonnegative_float(raw.get("value", ""), "value", row_number)
    lower = _nonnegative_float(raw.get("lower", ""), "lower", row_number)
    upper = _nonnegative_float(raw.get("upper", ""), "upper", row_number)
    if not lower <= estimate <= upper:
        raise RainfallIdfImportError(
            f"row {row_number}: expected lower <= value <= upper"
        )

    return RainfallIdfRow(
        source_station_name_he=station_name,
        source_station_id=station_source_ids[station_name],
        measure_type=measure_type,
        number_of_years=number_of_years,
        duration_minutes=duration,
        probability_percent=probability,
        return_period_years=return_period,
        estimate=estimate,
        lower_bound=lower,
        upper_bound=upper,
        match_method=(
            "manual_override" if station_name == "באר שבע" else "official_name_exact"
        ),
    )


def parse_rainfall_idf_csv(
    path: str | Path,
    *,
    station_source_ids: Mapping[str, int] | None = None,
) -> list[RainfallIdfRow]:
    """Parse a complete flat IMS IDF export and reject partial snapshots."""
    station_source_ids = station_source_ids or IDF_STATION_SOURCE_IDS
    source_path = Path(path)
    with source_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise RainfallIdfImportError(
                "IDF CSV columns must be: " + ", ".join(EXPECTED_COLUMNS)
            )
        rows = [
            _parse_row(raw, row_number, station_source_ids)
            for row_number, raw in enumerate(reader, start=2)
        ]

    expected_station_names = set(station_source_ids)
    actual_station_names = {row.source_station_name_he for row in rows}
    if actual_station_names != expected_station_names:
        missing = sorted(expected_station_names - actual_station_names)
        extra = sorted(actual_station_names - expected_station_names)
        raise RainfallIdfImportError(
            f"IDF station set mismatch; missing={missing}, extra={extra}"
        )

    expected_combinations = {
        (measure_type, duration, probability)
        for measure_type in EXPECTED_MEASURE_TYPES
        for duration in EXPECTED_DURATIONS
        for probability in EXPECTED_PROBABILITIES
    }
    station_combinations: dict[str, set[tuple[str, int, Decimal]]] = defaultdict(set)
    station_years: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        combination = (
            row.measure_type,
            row.duration_minutes,
            row.probability_percent,
        )
        combinations = station_combinations[row.source_station_name_he]
        if combination in combinations:
            raise RainfallIdfImportError(
                "duplicate IDF value for "
                f"{row.source_station_name_he!r}, {combination}"
            )
        combinations.add(combination)
        station_years[row.source_station_name_he].add(row.number_of_years)

    for station_name in sorted(expected_station_names):
        if station_combinations[station_name] != expected_combinations:
            raise RainfallIdfImportError(
                f"station {station_name!r} does not contain the complete IDF matrix"
            )
        if len(station_years[station_name]) != 1:
            raise RainfallIdfImportError(
                f"station {station_name!r} has inconsistent number_of_years"
            )

    return rows


_DELETE_VALUES = text(
    "DELETE FROM rain_station_idf_values WHERE rain_station_id IN :station_ids"
).bindparams(bindparam("station_ids", expanding=True))

_INSERT_VALUES = text(
    """
    INSERT INTO rain_station_idf_values (
      rain_station_id, source_station_name_he, measure_type, number_of_years,
      duration_minutes, probability_percent, return_period_years, estimate,
      lower_bound, upper_bound, match_method, source_dataset, imported_at
    ) VALUES (
      :rain_station_id, :source_station_name_he, :measure_type, :number_of_years,
      :duration_minutes, :probability_percent, :return_period_years, :estimate,
      :lower_bound, :upper_bound, :match_method, :source_dataset, :imported_at
    )
    """
)

_REFRESH_BASIN_LINKS = text(
    """
    INSERT INTO hydrometric_station_idf_links (
      hydrometric_station_id,
      rain_station_id,
      drainage_basin_id,
      distance_m,
      linked_at
    )
    SELECT hydrometric.id,
           rain.id,
           hydrometric.drainage_basin_id,
           ST_Distance(hydrometric.location, rain.location),
           :linked_at
    FROM hydrometric_stations AS hydrometric
    JOIN (
      SELECT DISTINCT station.id,
             station.location,
             station.drainage_basin_id
      FROM rain_stations AS station
      JOIN rain_station_idf_values AS idf
        ON idf.rain_station_id = station.id
      WHERE station.drainage_basin_id IS NOT NULL
    ) AS rain
      ON rain.drainage_basin_id = hydrometric.drainage_basin_id
    WHERE hydrometric.drainage_basin_id IS NOT NULL
    """
)


def _rain_station_ids(
    session: OrmSession, source_station_ids: Sequence[int]
) -> dict[int, int]:
    statement = text(
        """
        SELECT id, source_station_id
        FROM rain_stations
        WHERE source_station_id IN :source_station_ids
        """
    ).bindparams(bindparam("source_station_ids", expanding=True))
    rows = session.execute(
        statement, {"source_station_ids": list(source_station_ids)}
    ).mappings()
    result = {int(row["source_station_id"]): int(row["id"]) for row in rows}
    missing = sorted(set(source_station_ids) - set(result))
    if missing:
        raise RainfallIdfImportError(
            f"rain_stations is missing source_station_id values: {missing}"
        )
    return result


def refresh_hydrometric_idf_basin_links_in_session(
    session: OrmSession,
    *,
    linked_at: datetime | None = None,
) -> int:
    """Rebuild every same-basin hydrometric-to-IDF rain-station link."""
    linked_at = linked_at or datetime.now(timezone.utc)
    session.execute(text("DELETE FROM hydrometric_station_idf_links"))
    result = session.execute(_REFRESH_BASIN_LINKS, {"linked_at": linked_at})
    return result.rowcount


def import_rainfall_idf_csv(
    path: str | Path,
    *,
    session_factory=Session,
    imported_at: datetime | None = None,
) -> dict[str, int | str]:
    """Atomically replace the reconciled stations' IDF values."""
    rows = parse_rainfall_idf_csv(path)
    imported_at = imported_at or datetime.now(timezone.utc)
    source_station_ids = sorted({row.source_station_id for row in rows})

    with session_factory.begin() as session:
        rain_station_ids = _rain_station_ids(session, source_station_ids)
        internal_ids = sorted(rain_station_ids.values())
        session.execute(_DELETE_VALUES, {"station_ids": internal_ids})

        payload = [
            {
                "rain_station_id": rain_station_ids[row.source_station_id],
                "source_station_name_he": row.source_station_name_he,
                "measure_type": row.measure_type,
                "number_of_years": row.number_of_years,
                "duration_minutes": row.duration_minutes,
                "probability_percent": row.probability_percent,
                "return_period_years": row.return_period_years,
                "estimate": row.estimate,
                "lower_bound": row.lower_bound,
                "upper_bound": row.upper_bound,
                "match_method": row.match_method,
                "source_dataset": SOURCE_DATASET,
                "imported_at": imported_at,
            }
            for row in rows
        ]
        for start in range(0, len(payload), 1000):
            session.execute(_INSERT_VALUES, payload[start : start + 1000])
        basin_links = refresh_hydrometric_idf_basin_links_in_session(
            session, linked_at=imported_at
        )

    return {
        "stations": len(source_station_ids),
        "values": len(rows),
        "basin_links": basin_links,
        "source_dataset": SOURCE_DATASET,
    }
