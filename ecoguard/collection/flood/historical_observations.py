"""Import Water Authority hydrograph CSV files into a separate history cache.

Historical rows never enter the real-time observation stream. They are kept in
their own auditable tables and are joined to live stations only while static
monthly baselines are rebuilt.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text


SOURCE = "water_authority_historical_hydrographs"
CSV_ENCODING = "cp1255"
SOURCE_TIMEZONE = ZoneInfo("Asia/Jerusalem")
SOURCE_TIMESTAMP_FORMAT = "%d/%m/%Y %H:%M:%S"
HYDROLOGICAL_YEAR_PATTERN = re.compile(r"^(\d{4})/(\d{4})$")
INSERT_BATCH_SIZE = 5_000
SEWAGE_FLOW_TYPE = "ביוב"

FIELD_STATION_ID = "זיהוי תחנה"
FIELD_STATION_NAME_HE = "שם תחנה"
FIELD_STATION_NAME_EN = "שם תחנה באנגלית"
FIELD_HYDROLOGICAL_YEAR = "שנה הידרולוגית"
FIELD_OBSERVED_AT = "זמן מדידת ספיקה"
FIELD_WATER_HEIGHT = "רום המים (מ')"
FIELD_DISCHARGE = "ספיקה (מ''ק/שנייה)"
FIELD_DATA_TYPE = "סוג נתון"
FIELD_FLOW_TYPE = "סוג זרימה"
FIELD_RECORD_TYPE = "סוג רשומה"

EXPECTED_FIELDS = (
    FIELD_STATION_ID,
    FIELD_STATION_NAME_HE,
    FIELD_STATION_NAME_EN,
    FIELD_HYDROLOGICAL_YEAR,
    FIELD_OBSERVED_AT,
    FIELD_WATER_HEIGHT,
    FIELD_DISCHARGE,
    FIELD_DATA_TYPE,
    FIELD_FLOW_TYPE,
    FIELD_RECORD_TYPE,
)


class HistoricalHydrographError(ValueError):
    """A hydrograph file cannot be imported without guessing its meaning."""


@dataclass(frozen=True)
class HistoricalHydrographFile:
    path: Path
    source_name: str
    checksum: str
    size_bytes: int
    row_count: int
    station_ids: frozenset[int]
    first_observed_at: datetime
    last_observed_at: datetime


def _required_text(row: Mapping[str, Any], field: str, row_number: int) -> str:
    value = row.get(field)
    result = "" if value is None else str(value).strip()
    if not result:
        raise HistoricalHydrographError(
            f"row {row_number} is missing required field {field}"
        )
    return result


def _optional_text(row: Mapping[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _station_id(value: str, row_number: int) -> int:
    try:
        station_id = int(value)
    except (TypeError, ValueError) as error:
        raise HistoricalHydrographError(
            f"row {row_number} has an invalid station id"
        ) from error
    if station_id <= 0:
        raise HistoricalHydrographError(
            f"row {row_number} station id must be positive"
        )
    return station_id


def _measurement(
    value: Any,
    field: str,
    row_number: int,
    *,
    nonnegative: bool = False,
) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise HistoricalHydrographError(
            f"row {row_number} has an invalid {field}"
        ) from error
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise HistoricalHydrographError(
            f"row {row_number} has an invalid {field}"
        )
    return result


def _observed_at(value: str, row_number: int) -> datetime:
    try:
        local_time = datetime.strptime(value, SOURCE_TIMESTAMP_FORMAT).replace(
            tzinfo=SOURCE_TIMEZONE
        )
    except ValueError as error:
        raise HistoricalHydrographError(
            f"row {row_number} has an invalid observation timestamp"
        ) from error
    return local_time.astimezone(timezone.utc)


def _hydrological_year(value: str, row_number: int) -> str:
    match = HYDROLOGICAL_YEAR_PATTERN.fullmatch(value)
    if match is None or int(match.group(2)) != int(match.group(1)) + 1:
        raise HistoricalHydrographError(
            f"row {row_number} has an invalid hydrological year"
        )
    return value


def parse_historical_hydrograph_row(
    row: Mapping[str, Any],
    *,
    source_row_number: int,
) -> dict[str, Any]:
    """Validate and normalize one source row without changing its identity."""
    if None in row:
        raise HistoricalHydrographError(
            f"row {source_row_number} contains more columns than the header"
        )

    station_name_he = _optional_text(row, FIELD_STATION_NAME_HE)
    station_name_en = _optional_text(row, FIELD_STATION_NAME_EN)
    if station_name_he is None and station_name_en is None:
        raise HistoricalHydrographError(
            f"row {source_row_number} has no station name"
        )

    water_height = _measurement(
        row.get(FIELD_WATER_HEIGHT),
        "water height",
        source_row_number,
    )
    discharge = _measurement(
        row.get(FIELD_DISCHARGE),
        "discharge",
        source_row_number,
        nonnegative=True,
    )
    if water_height is None and discharge is None:
        raise HistoricalHydrographError(
            f"row {source_row_number} contains no measurement"
        )

    flow_type = _required_text(row, FIELD_FLOW_TYPE, source_row_number)
    return {
        "source_row_number": source_row_number,
        "historical_station_id": _station_id(
            _required_text(row, FIELD_STATION_ID, source_row_number),
            source_row_number,
        ),
        "station_name_he": station_name_he,
        "station_name_en": station_name_en,
        "hydrological_year": _hydrological_year(
            _required_text(row, FIELD_HYDROLOGICAL_YEAR, source_row_number),
            source_row_number,
        ),
        "observed_at": _observed_at(
            _required_text(row, FIELD_OBSERVED_AT, source_row_number),
            source_row_number,
        ),
        "water_height_m": water_height,
        "discharge_m3s": discharge,
        "data_type": _required_text(row, FIELD_DATA_TYPE, source_row_number),
        "flow_type": flow_type,
        "record_type": _required_text(row, FIELD_RECORD_TYPE, source_row_number),
        "is_sewage": flow_type == SEWAGE_FLOW_TYPE,
    }


def iter_historical_hydrograph_rows(
    path: str | Path,
) -> Iterator[dict[str, Any]]:
    """Stream a CP1255 source file so large histories are never held in RAM."""
    source_path = Path(path)
    try:
        handle = source_path.open("r", encoding=CSV_ENCODING, newline="")
    except OSError as error:
        raise HistoricalHydrographError(
            f"cannot open hydrograph file {source_path.name}"
        ) from error

    with handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != EXPECTED_FIELDS:
            raise HistoricalHydrographError(
                f"hydrograph file {source_path.name} has an unexpected header"
            )
        for row in reader:
            yield parse_historical_hydrograph_row(
                row,
                source_row_number=reader.line_num,
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise HistoricalHydrographError(
            f"cannot read hydrograph file {path.name}"
        ) from error
    return digest.hexdigest()


def inspect_historical_hydrograph_file(
    path: str | Path,
) -> HistoricalHydrographFile:
    """Validate a file and collect the metadata required for an atomic import."""
    source_path = Path(path).resolve()
    station_ids: set[int] = set()
    row_count = 0
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None

    for row in iter_historical_hydrograph_rows(source_path):
        row_count += 1
        station_ids.add(row["historical_station_id"])
        observed_at = row["observed_at"]
        if first_observed_at is None or observed_at < first_observed_at:
            first_observed_at = observed_at
        if last_observed_at is None or observed_at > last_observed_at:
            last_observed_at = observed_at

    if row_count == 0 or first_observed_at is None or last_observed_at is None:
        raise HistoricalHydrographError(
            f"hydrograph file {source_path.name} contains no observations"
        )

    return HistoricalHydrographFile(
        path=source_path,
        source_name=source_path.name,
        checksum=_sha256(source_path),
        size_bytes=source_path.stat().st_size,
        row_count=row_count,
        station_ids=frozenset(station_ids),
        first_observed_at=first_observed_at,
        last_observed_at=last_observed_at,
    )


INSERT_IMPORT = text(
    """
    INSERT INTO historical_hydrograph_imports (
      source_name, content_sha256, source_size_bytes, row_count, station_count,
      first_observed_at, last_observed_at, imported_at
    ) VALUES (
      :source_name, :content_sha256, :source_size_bytes, :row_count,
      :station_count, :first_observed_at, :last_observed_at, :imported_at
    )
    RETURNING id
    """
)


INSERT_OBSERVATION = text(
    """
    INSERT INTO historical_hydrometric_observations (
      import_id, source_row_number, historical_station_id,
      station_name_he, station_name_en, hydrological_year, observed_at,
      water_height_m, discharge_m3s, data_type, flow_type, record_type,
      is_sewage
    ) VALUES (
      :import_id, :source_row_number, :historical_station_id,
      :station_name_he, :station_name_en, :hydrological_year, :observed_at,
      :water_height_m, :discharge_m3s, :data_type, :flow_type, :record_type,
      :is_sewage
    )
    """
)


def _batches(
    rows: Iterable[dict[str, Any]],
    *,
    size: int = INSERT_BATCH_SIZE,
) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def persist_historical_hydrograph_file(
    source: HistoricalHydrographFile,
) -> dict[str, int]:
    """Replace one changed source atomically and skip identical content."""
    from ecoguard.database.engine import Session

    with Session() as session:
        existing_content = session.execute(
            text(
                """
                SELECT id, row_count
                FROM historical_hydrograph_imports
                WHERE content_sha256 = :checksum
                """
            ),
            {"checksum": source.checksum},
        ).mappings().one_or_none()
        if existing_content is not None:
            session.commit()
            return {
                "files_imported": 0,
                "files_unchanged": 1,
                "rows_written": 0,
                "source_rows": int(existing_content["row_count"]),
                "stations_seen": len(source.station_ids),
            }

        known_station_ids = set(
            session.execute(
                text(
                    "SELECT source_station_id "
                    "FROM historical_hydrometric_stations"
                )
            ).scalars()
        )
        unknown_station_ids = sorted(source.station_ids - known_station_ids)
        if unknown_station_ids:
            preview = ", ".join(str(value) for value in unknown_station_ids[:10])
            raise HistoricalHydrographError(
                "hydrograph file references stations missing from the official "
                f"registry: {preview}"
            )

        previous_import_id = session.execute(
            text(
                "SELECT id FROM historical_hydrograph_imports "
                "WHERE source_name = :source_name"
            ),
            {"source_name": source.source_name},
        ).scalar_one_or_none()
        if previous_import_id is not None:
            session.execute(
                text("DELETE FROM historical_hydrograph_imports WHERE id = :id"),
                {"id": previous_import_id},
            )

        imported_at = datetime.now(timezone.utc)
        import_id = session.execute(
            INSERT_IMPORT,
            {
                "source_name": source.source_name,
                "content_sha256": source.checksum,
                "source_size_bytes": source.size_bytes,
                "row_count": source.row_count,
                "station_count": len(source.station_ids),
                "first_observed_at": source.first_observed_at,
                "last_observed_at": source.last_observed_at,
                "imported_at": imported_at,
            },
        ).scalar_one()

        rows_written = 0
        for batch in _batches(iter_historical_hydrograph_rows(source.path)):
            for row in batch:
                row["import_id"] = import_id
            session.execute(INSERT_OBSERVATION, batch)
            rows_written += len(batch)

        if rows_written != source.row_count:
            raise HistoricalHydrographError(
                f"hydrograph file changed while it was being imported: "
                f"expected {source.row_count} rows, read {rows_written}"
            )
        if _sha256(source.path) != source.checksum:
            raise HistoricalHydrographError(
                "hydrograph file changed while it was being imported: "
                "content checksum no longer matches"
            )
        session.commit()

    return {
        "files_imported": 1,
        "files_unchanged": 0,
        "rows_written": rows_written,
        "source_rows": source.row_count,
        "stations_seen": len(source.station_ids),
    }


def load_historical_hydrograph_files(
    paths: Iterable[str | Path],
) -> dict[str, int]:
    """Validate and cache local hydrograph exports; scheduling is not involved."""
    from ecoguard.database.repositories.collector_runs import log_finish, log_start

    run_id = log_start(SOURCE)
    totals = {
        "files_imported": 0,
        "files_unchanged": 0,
        "rows_written": 0,
        "source_rows": 0,
        "stations_seen": 0,
    }
    try:
        all_station_ids: set[int] = set()
        sources = [inspect_historical_hydrograph_file(path) for path in paths]
        if not sources:
            raise HistoricalHydrographError("at least one hydrograph file is required")
        for source in sources:
            result = persist_historical_hydrograph_file(source)
            for key in (
                "files_imported",
                "files_unchanged",
                "rows_written",
                "source_rows",
            ):
                totals[key] += result[key]
            all_station_ids.update(source.station_ids)
        totals["stations_seen"] = len(all_station_ids)
        log_finish(run_id, status="ok", rows_written=totals["rows_written"])
        return totals
    except Exception as error:
        log_finish(run_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise
