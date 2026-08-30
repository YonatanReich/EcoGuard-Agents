"""Build normalized open-area fire statistics from official data.gov.il data.

The source rows are aggregated statistics, not individual incidents. This
module is intentionally independent from the production detection pipeline.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


PACKAGE_ID = "eventsdistrict"
CKAN_API = "https://data.gov.il/api/3/action/package_show"
DATASTORE_API = "https://data.gov.il/api/3/action/datastore_search"
EXPECTED_ORGANIZATION = "firefightingcommission"
USER_AGENT = "EcoGuard-Agents historical-fire-ground-truth-builder/1.0"
REQUEST_TIMEOUT_SECONDS = 60
PAGE_SIZE = 5000
MAX_RESOURCE_ROWS = 1_000_000
REQUEST_PAUSE_SECONDS = 0.2
TARGET_YEARS = frozenset(range(2023, 2027))
OUTPUT_PATH = Path("data/generated/israel_fire_rescue_open_area_2023_2026.csv")
SOURCE_NAME = "israel_fire_and_rescue"

OUTPUT_FIELDS = (
    "year",
    "month",
    "district",
    "event_domain",
    "event_type",
    "scenario",
    "settlement",
    "settlement_lamas_code",
    "event_count",
    "source",
    "source_resource",
    "source_updated_at",
)


class HistoricalFireDataError(RuntimeError):
    """Safe provider or source-data error."""


def normalize_column_name(value: object) -> str:
    """Normalize headers conservatively across Hebrew/English resources."""
    text = str(value or "").lstrip("\ufeff").strip().casefold()
    return re.sub(r"[^0-9a-z\u0590-\u05ff]+", "", text)


FIELD_ALIASES = {
    "year": ("year", "eventyear", "שנה", "שנתאירוע"),
    "month": ("month", "eventmonth", "חודש", "חודשאירוע"),
    "district": ("district", "districtname", "מחוז", "שםמחוז"),
    "event_domain": (
        "eventdomain",
        "domain",
        "eventareadesc",
        "eventarea",
        "תחום",
        "תחוםאירוע",
    ),
    "event_type": (
        "eventtype",
        "eventtypedesc",
        "type",
        "מתאר",
        "סוגאירוע",
    ),
    "scenario": (
        "scenario",
        "eventscenario",
        "eventscenariodesc",
        "תרחיש",
    ),
    "settlement": (
        "settlement",
        "settlementname",
        "location",
        "מיקום",
        "ישוב",
        "יישוב",
    ),
    "settlement_lamas_code": (
        "settlementlamascode",
        "settlementcode",
        "lamascode",
        "סמלישוב",
        "סמליישוב",
    ),
    "event_count": (
        "eventcount",
        "eventsnumber",
        "numberofevents",
        "count",
        "מספראירועים",
        "כמותאירועים",
    ),
}

REQUIRED_FIELDS = frozenset(
    {"year", "month", "event_domain", "event_type", "event_count"}
)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\ufeff", " ")).strip()


def _canonical_value(value: object) -> str:
    return re.sub(r"[^0-9a-z\u0590-\u05ff]+", "", _clean_text(value).casefold())


def parse_event_count(value: object) -> int | None:
    """Parse a non-negative aggregate count without expanding it."""
    text = _clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number < 0 or not number.is_integer():
        return None
    return int(number)


def _parse_integer(value: object) -> int | None:
    text = _clean_text(value)
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def resolve_columns(headers: Iterable[object]) -> dict[str, str]:
    normalized_headers = {normalize_column_name(header): str(header) for header in headers}
    resolved: dict[str, str] = {}
    for logical_name, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            original = normalized_headers.get(normalize_column_name(alias))
            if original is not None:
                resolved[logical_name] = original
                break
    return resolved


def _is_fire_domain(value: object) -> bool:
    return _canonical_value(value) in {"fire", "fires", "שריפה", "שריפות"}


def _is_open_area_type(value: object) -> bool:
    return _canonical_value(value) in {
        "openarea",
        "openareas",
        "openspaces",
        "שטחפתוח",
        "שטחיםפתוחים",
    }


def normalize_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_resource: str,
    source_updated_at: str | None,
    target_years: frozenset[int] = TARGET_YEARS,
) -> tuple[list[dict[str, Any]], int]:
    """Normalize, filter, and deduplicate official aggregate rows.

    Returns normalized rows and the number of malformed rows skipped.
    """
    rows = list(rows)
    if not rows:
        return [], 0
    columns = resolve_columns(rows[0].keys())
    missing = REQUIRED_FIELDS - columns.keys()
    if missing:
        raise HistoricalFireDataError(
            "Official resource is missing required columns: " + ", ".join(sorted(missing))
        )

    normalized: list[dict[str, Any]] = []
    malformed = 0
    for row in rows:
        year = _parse_integer(row.get(columns["year"]))
        month = _parse_integer(row.get(columns["month"]))
        count = parse_event_count(row.get(columns["event_count"]))
        if year is None or month is None or not 1 <= month <= 12 or count is None:
            malformed += 1
            continue
        if year not in target_years:
            continue
        if not _is_fire_domain(row.get(columns["event_domain"])):
            continue
        if not _is_open_area_type(row.get(columns["event_type"])):
            continue

        def optional(name: str) -> str:
            column = columns.get(name)
            return _clean_text(row.get(column)) if column else ""

        normalized.append(
            {
                "year": year,
                "month": month,
                "district": optional("district"),
                "event_domain": "שריפה",
                "event_type": "שטחים פתוחים",
                "scenario": optional("scenario"),
                "settlement": optional("settlement"),
                "settlement_lamas_code": optional("settlement_lamas_code"),
                "event_count": count,
                "source": SOURCE_NAME,
                "source_resource": source_resource,
                "source_updated_at": _clean_text(source_updated_at),
            }
        )
    return normalized, malformed


def deduplicate_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove exact logical duplicates, including duplicates across resources."""
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    identity_fields = OUTPUT_FIELDS[:9]
    for record in records:
        key = tuple(record.get(field) for field in identity_fields)
        existing = unique.get(key)
        if existing is None or str(record.get("source_updated_at", "")) > str(
            existing.get("source_updated_at", "")
        ):
            unique[key] = record
    return sorted(
        unique.values(),
        key=lambda row: (
            row["year"],
            row["month"],
            row["district"],
            row["settlement"],
            row["scenario"],
        ),
    )


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise HistoricalFireDataError(f"Official provider returned HTTP {error.code}.") from None
    except urllib.error.URLError as error:
        reason = "timeout" if isinstance(error.reason, TimeoutError) else "network error"
        raise HistoricalFireDataError(f"Official provider {reason}.") from None
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        raise HistoricalFireDataError("Official provider returned an invalid response.") from None
    if not isinstance(result, dict):
        raise HistoricalFireDataError("Official provider returned an invalid response.")
    return result


def discover_resources() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    url = f"{CKAN_API}?{urllib.parse.urlencode({'id': PACKAGE_ID})}"
    payload = _request_json(url)
    if payload.get("success") is not True or not isinstance(payload.get("result"), dict):
        raise HistoricalFireDataError("Official dataset metadata lookup failed.")
    package = payload["result"]
    organization = package.get("organization") or {}
    if organization.get("name") != EXPECTED_ORGANIZATION:
        raise HistoricalFireDataError("Official dataset publisher validation failed.")

    resources = []
    for resource in package.get("resources") or []:
        if resource.get("state") == "deleted":
            continue
        if str(resource.get("format") or "").upper() != "CSV":
            continue
        name = _clean_text(resource.get("name"))
        years = {int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", name)}
        if years and not years.intersection(TARGET_YEARS):
            continue
        if not years:
            continue
        if not resource.get("id") or not resource.get("url"):
            continue
        resources.append(resource)
    if not resources:
        raise HistoricalFireDataError("No official CSV resources were found for 2023-2026.")
    return package, resources


def _datastore_rows(resource: Mapping[str, Any]) -> list[dict[str, Any]]:
    resource_id = str(resource["id"])
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        parameters = {"resource_id": resource_id, "limit": PAGE_SIZE, "offset": offset}
        if offset:
            time.sleep(REQUEST_PAUSE_SECONDS)
        payload = _request_json(f"{DATASTORE_API}?{urllib.parse.urlencode(parameters)}")
        if payload.get("success") is not True:
            raise HistoricalFireDataError(
                f"DataStore request failed for resource {resource_id}."
            )
        result = payload.get("result") or {}
        page = result.get("records") or []
        if not isinstance(page, list):
            raise HistoricalFireDataError(
                f"DataStore returned malformed rows for resource {resource_id}."
            )
        rows.extend(page)
        if len(rows) > MAX_RESOURCE_ROWS:
            raise HistoricalFireDataError(
                f"Resource {resource_id} exceeds the row safety limit."
            )
        total = int(result.get("total") or len(rows))
        if not page or len(rows) >= total:
            return rows
        offset += len(page)


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1255"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise HistoricalFireDataError("Official CSV has an unsupported encoding.")


def _download_csv(resource: Mapping[str, Any]) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        str(resource["url"]),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv, application/csv, application/octet-stream;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content = response.read()
    except urllib.error.HTTPError as error:
        raise HistoricalFireDataError(
            f"Official resource {resource.get('id')} returned HTTP {error.code}."
        ) from None
    except urllib.error.URLError as error:
        reason = "timeout" if isinstance(error.reason, TimeoutError) else "network error"
        raise HistoricalFireDataError(
            f"Official resource {resource.get('id')} failed: {reason}."
        ) from None
    text = _decode_csv(content)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def fetch_resource_rows(resource: Mapping[str, Any]) -> list[dict[str, Any]]:
    if resource.get("datastore_active") is True:
        return _datastore_rows(resource)
    return _download_csv(resource)


def build_dataset(output_path: Path = OUTPUT_PATH) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    _, resources = discover_resources()
    all_records: list[dict[str, Any]] = []
    malformed = 0
    for resource in resources:
        rows = fetch_resource_rows(resource)
        records, skipped = normalize_records(
            rows,
            source_resource=str(resource.get("id")),
            source_updated_at=resource.get("last_modified")
            or resource.get("metadata_modified"),
        )
        all_records.extend(records)
        malformed += skipped
    records = deduplicate_records(all_records)
    if not records:
        raise HistoricalFireDataError("No matching official open-area fire records were found.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
        temporary.replace(output_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return records, resources, malformed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    try:
        records, resources, malformed = build_dataset(args.output)
    except HistoricalFireDataError as error:
        print(f"Historical fire dataset build failed: {error}")
        return 1
    print(f"Discovered resources: {len(resources)}")
    print(f"Normalized open-area rows: {len(records)}")
    print(f"Total event_count: {sum(row['event_count'] for row in records)}")
    print(f"Malformed rows skipped: {malformed}")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
