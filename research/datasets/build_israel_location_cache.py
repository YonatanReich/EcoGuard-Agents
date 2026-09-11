"""Build the offline Israeli locality/street cache from data.gov.il.

Run manually from the repository root. The application never imports or runs
this script, and the generated database and manifest are ignored by Git.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agents.hebrew_fire_location_extractor import (
    CACHE_PATH,
    CACHE_SCHEMA_SQL,
    normalize_location_name,
)


CKAN_API = "https://data.gov.il/api/3/action/package_show"
DATASTORE_API = "https://data.gov.il/api/3/action/datastore_search"
USER_AGENT = "EcoGuard-Agents location-cache-builder/1.0"
DATASTORE_PAGE_SIZE = 5000
MAX_DATASTORE_ROWS = 1_000_000
REQUEST_PAUSE_SECONDS = 0.2
DATASETS = {
    "localities": "citiesandsettelments",
    "streets": "321",
    "street_synonyms": "israel-streets-synom",
}

FIELD_ALIASES = {
    "locality_code": ("city_code", "סמל_ישוב"),
    "locality_name": ("city_name_he", "city_name", "שם_ישוב"),
    "street_code": ("street_code", "סמל_רחוב"),
    "street_name": ("street_name", "שם_רחוב"),
    "street_status": ("street_name_status",),
    "official_code": ("official_code",),
}


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _discover_csv_resource(dataset_id: str) -> dict:
    metadata = _fetch_json(
        f"{CKAN_API}?{urllib.parse.urlencode({'id': dataset_id})}"
    )
    if not metadata.get("success"):
        raise RuntimeError(f"Dataset metadata lookup failed for {dataset_id}.")

    dataset = metadata["result"]
    organization = dataset.get("organization") or {}
    if organization.get("name") != "population_authority":
        raise RuntimeError(
            f"Dataset {dataset_id} is not published by the expected authority."
        )

    resources = dataset.get("resources", [])
    candidates = [
        resource
        for resource in resources
        if str(resource.get("format", "")).upper() == "CSV"
        and resource.get("url")
        and resource.get("state") != "deleted"
    ]
    if not candidates:
        raise RuntimeError(f"No active CSV resource found for {dataset_id}.")

    def resource_rank(resource: dict) -> tuple[int, str]:
        name = str(resource.get("name", ""))
        current = int("מתעדכן" in name)
        updated = str(
            resource.get("last_modified")
            or resource.get("metadata_modified")
            or resource.get("created")
            or ""
        )
        return current, updated

    return max(candidates, key=resource_rank)


def _records_to_csv(records: list[dict], field_names: list[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode("utf-8-sig")


def _fetch_datastore(dataset_name: str, resource: dict) -> tuple[bytes, dict]:
    resource_id = resource.get("id")
    if not resource_id:
        raise RuntimeError(f"DataStore resource for {dataset_name} has no ID.")

    metadata_url = f"{DATASTORE_API}?{urllib.parse.urlencode({'resource_id': resource_id, 'limit': 0})}"
    try:
        metadata = _fetch_json(metadata_url)
    except urllib.error.HTTPError as error:
        if error.code == 403:
            raise RuntimeError(
                f"HTTP 403 fetching dataset {dataset_name}, resource {resource_id}."
            ) from error
        raise

    if not metadata.get("success"):
        raise RuntimeError(
            f"DataStore metadata lookup failed for {dataset_name}, resource {resource_id}."
        )

    result = metadata["result"]
    total = int(result.get("total", 0))
    if total <= 0:
        raise RuntimeError(
            f"DataStore returned no rows for {dataset_name}, resource {resource_id}."
        )
    if total > MAX_DATASTORE_ROWS:
        raise RuntimeError(
            f"DataStore row count for {dataset_name} exceeds the safety limit."
        )

    field_names = [field["id"] for field in result.get("fields", [])]
    if not field_names:
        raise RuntimeError(
            f"DataStore returned no fields for {dataset_name}, resource {resource_id}."
        )

    sort = "_id asc" if "_id" in field_names else None
    records = []
    offset = 0
    while offset < total:
        parameters = {
            "resource_id": resource_id,
            "limit": min(DATASTORE_PAGE_SIZE, total - offset),
            "offset": offset,
        }
        if sort:
            parameters["sort"] = sort
        page_url = f"{DATASTORE_API}?{urllib.parse.urlencode(parameters)}"

        if offset:
            time.sleep(REQUEST_PAUSE_SECONDS)
        try:
            page = _fetch_json(page_url)
        except urllib.error.HTTPError as error:
            if error.code == 403:
                raise RuntimeError(
                    f"HTTP 403 fetching dataset {dataset_name}, resource {resource_id}."
                ) from error
            raise

        if not page.get("success"):
            raise RuntimeError(
                f"DataStore page failed for {dataset_name}, resource {resource_id}."
            )
        page_records = page["result"].get("records", [])
        if not page_records:
            raise RuntimeError(
                f"DataStore pagination ended early for {dataset_name}, resource {resource_id}."
            )
        records.extend(page_records)
        offset += len(page_records)

    content = _records_to_csv(records, field_names)
    return content, {
        "acquisition": "datastore_search",
        "datastore_url": DATASTORE_API,
        "datastore_rows": len(records),
        "resource_id": resource_id,
        "resource_name": resource.get("name"),
        "resource_url": resource.get("url"),
        "resource_updated_at": resource.get("last_modified"),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _download_resource(dataset_name: str, resource: dict) -> tuple[bytes, dict]:
    if resource.get("datastore_active") is True:
        return _fetch_datastore(dataset_name, resource)

    resource_id = resource.get("id") or "unknown"
    request = urllib.request.Request(
        resource["url"],
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/csv, application/csv, application/octet-stream;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 403:
            raise RuntimeError(
                f"HTTP 403 fetching dataset {dataset_name}, resource {resource_id}."
            ) from error
        raise

    return content, {
        "acquisition": "resource_url",
        "resource_id": resource_id,
        "resource_name": resource.get("name"),
        "resource_url": resource.get("url"),
        "resource_updated_at": resource.get("last_modified"),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1255"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError("Official CSV is neither UTF-8 nor Windows-1255.")


def _rows(content: bytes) -> tuple[list[dict], set[str]]:
    reader = csv.DictReader(io.StringIO(_decode_csv(content)))
    if reader.fieldnames is None:
        raise RuntimeError("Official CSV has no header row.")
    rows = list(reader)
    if not rows:
        raise RuntimeError("Official CSV contains no data rows.")
    return rows, set(reader.fieldnames)


def _field(headers: set[str], logical_name: str) -> str:
    for candidate in FIELD_ALIASES[logical_name]:
        if candidate in headers:
            return candidate
    raise RuntimeError(
        f"Official dataset is missing the required {logical_name} column."
    )


def _integer(value: object, field_name: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"Invalid numeric value in {field_name}.") from error


def _build_database(
    database_path: Path,
    locality_rows: list[dict],
    locality_headers: set[str],
    street_rows: list[dict],
    street_headers: set[str],
    synonym_rows: list[dict],
    synonym_headers: set[str],
) -> dict:
    locality_code_field = _field(locality_headers, "locality_code")
    locality_name_field = _field(locality_headers, "locality_name")
    street_city_field = _field(street_headers, "locality_code")
    street_code_field = _field(street_headers, "street_code")
    street_name_field = _field(street_headers, "street_name")
    synonym_city_field = _field(synonym_headers, "locality_code")
    synonym_name_field = _field(synonym_headers, "street_name")
    synonym_status_field = _field(synonym_headers, "street_status")
    synonym_official_field = _field(synonym_headers, "official_code")

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(CACHE_SCHEMA_SQL)

        for row in locality_rows:
            code = _integer(row[locality_code_field], locality_code_field)
            name = str(row[locality_name_field]).strip()
            if not name:
                continue
            normalized = normalize_location_name(name)
            connection.execute(
                "INSERT OR REPLACE INTO localities VALUES (?, ?, ?)",
                (code, name, normalized),
            )
            connection.execute(
                "INSERT OR REPLACE INTO locality_names VALUES (?, ?, ?, ?)",
                (code, name, normalized, "official"),
            )

        for row in street_rows:
            city_code = _integer(row[street_city_field], street_city_field)
            street_code = _integer(row[street_code_field], street_code_field)
            name = str(row[street_name_field]).strip()
            if not name or connection.execute(
                "SELECT 1 FROM localities WHERE locality_code = ?",
                (city_code,),
            ).fetchone() is None:
                continue
            normalized = normalize_location_name(name)
            connection.execute(
                "INSERT OR REPLACE INTO streets VALUES (?, ?, ?, ?)",
                (city_code, street_code, name, normalized),
            )
            connection.execute(
                "INSERT OR REPLACE INTO street_names VALUES (?, ?, ?, ?, ?)",
                (city_code, street_code, name, normalized, "official"),
            )

        for row in synonym_rows:
            city_code = _integer(row[synonym_city_field], synonym_city_field)
            official_code = _integer(
                row[synonym_official_field], synonym_official_field
            )
            name = str(row[synonym_name_field]).strip()
            if not name or connection.execute(
                """
                SELECT 1 FROM streets
                WHERE locality_code = ? AND street_code = ?
                """,
                (city_code, official_code),
            ).fetchone() is None:
                continue
            status = str(row[synonym_status_field]).strip() or "synonym"
            connection.execute(
                "INSERT OR IGNORE INTO street_names VALUES (?, ?, ?, ?, ?)",
                (
                    city_code,
                    official_code,
                    name,
                    normalize_location_name(name),
                    status,
                ),
            )

        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("Generated SQLite cache failed its integrity check.")
        return {
            "localities": connection.execute(
                "SELECT count(*) FROM localities"
            ).fetchone()[0],
            "streets": connection.execute("SELECT count(*) FROM streets").fetchone()[0],
            "street_names": connection.execute(
                "SELECT count(*) FROM street_names"
            ).fetchone()[0],
        }
    finally:
        connection.close()


def build_cache(output_path: Path = CACHE_PATH) -> None:
    resources = {
        name: _discover_csv_resource(dataset_id)
        for name, dataset_id in DATASETS.items()
    }
    downloads = {
        name: _download_resource(name, resource)
        for name, resource in resources.items()
    }
    parsed = {name: _rows(content) for name, (content, _) in downloads.items()}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        prefix="israel_locations_",
        suffix=".sqlite3",
        dir=output_path.parent,
        delete=False,
    )
    temporary_path = Path(temporary.name)
    temporary.close()

    try:
        counts = _build_database(
            temporary_path,
            *parsed["localities"],
            *parsed["streets"],
            *parsed["street_synonyms"],
        )
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    manifest = {
        "cache_schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "publisher": "Population and Immigration Authority",
        "counts": counts,
        "sources": {
            name: {
                "dataset_id": DATASETS[name],
                **provenance,
            }
            for name, (_, provenance) in downloads.items()
        },
    }
    manifest_path = output_path.with_name("israel_locations.manifest.json")
    manifest_temporary = manifest_path.with_suffix(".json.tmp")
    manifest_temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(manifest_temporary, manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=CACHE_PATH)
    arguments = parser.parse_args()
    build_cache(arguments.output)
    print("Official Israeli location cache built successfully.")


if __name__ == "__main__":
    main()
