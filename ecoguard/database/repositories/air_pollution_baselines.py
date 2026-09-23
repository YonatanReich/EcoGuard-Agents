"""Set-based, transactional persistence for validated compact baseline plans."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, insert, select, tuple_

from ecoguard.database.engine import Session
from ecoguard.database.models import (
    AirPollutionBaselineBucket, AirPollutionBaselineProfile,
    AirPollutionBaselineVersion, AirPollutionStationCatalog,
)

IDENTITY_FIELDS = (
    "provider", "station_id", "channel_id", "pollutant", "canonical_unit",
    "baseline_family",
)
# 2,000 * 16 bucket values is ~32k binds, conservative against PostgreSQL's
# 65,535 parameter ceiling while halving round trips from the original 1,000.
BUCKET_CHUNK_SIZE = 2000
Progress = Callable[[str], None]


def _notify(progress: Progress | None, message: str) -> None:
    """Report progress, when a caller asked to be kept informed."""
    if progress is not None:
        progress(message)


def _identity(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    """What makes one baseline row distinct from another."""
    return tuple(row[field] for field in IDENTITY_FIELDS)  # type: ignore[return-value]


def _mapping_rows(result) -> list[dict[str, Any]]:
    """Query rows as plain dictionaries."""
    return [dict(row) for row in result.mappings().all()]


def _unique(rows, key, label):
    """Reject a set of rows containing the same thing twice."""
    mapped = {}
    for row in rows:
        row_key = key(row)
        if row_key in mapped:
            raise ValueError(f"duplicate {label} in import plan: {row_key}")
        mapped[row_key] = row
    return mapped


def persist_import_plan(
    session,
    plan: dict[str, Any],
    *,
    imported_at: datetime,
    progress: Progress | None = None,
) -> dict[str, int]:
    """Persist an all-or-nothing plan as drafts; the caller owns the transaction."""
    if imported_at.utcoffset() is None:
        raise ValueError("imported_at must carry a UTC offset")
    if plan.get("plan_schema") != "air-pollution-baseline-import-plan-v1" or not plan.get("dry_run"):
        raise ValueError("only a validated dry-run plan is accepted")
    counts = {"stations_inserted": 0, "profiles_inserted": 0,
              "versions_inserted": 0, "buckets_inserted": 0, "versions_existing": 0}

    _notify(progress, "station catalog")
    station_plan = _unique(
        plan["station_catalog"], lambda row: (row["provider"], row["station_id"]), "station",
    )
    station_keys = list(station_plan)
    existing_station_rows = []
    if station_keys:
        existing_station_rows = _mapping_rows(session.execute(select(
            AirPollutionStationCatalog.provider,
            AirPollutionStationCatalog.station_id,
            AirPollutionStationCatalog.station_name,
            AirPollutionStationCatalog.availability,
            AirPollutionStationCatalog.artifact_sha256,
        ).where(tuple_(
            AirPollutionStationCatalog.provider,
            AirPollutionStationCatalog.station_id,
        ).in_(station_keys))))
    existing_stations = {(r["provider"], r["station_id"]): r for r in existing_station_rows}
    for key, existing in existing_stations.items():
        proposed = station_plan[key]
        if any(existing[field] != proposed[field] for field in
               ("station_name", "availability", "artifact_sha256")):
            raise ValueError(f"station catalog conflict: {key}")
    missing_station_rows = [
        {**row, "imported_at": imported_at}
        for key, row in station_plan.items() if key not in existing_stations
    ]
    if missing_station_rows:
        returned = _mapping_rows(session.execute(
            insert(AirPollutionStationCatalog).returning(
                AirPollutionStationCatalog.provider, AirPollutionStationCatalog.station_id,
            ), missing_station_rows,
        ))
        returned_keys = {(r["provider"], r["station_id"]) for r in returned}
        expected_keys = {(r["provider"], r["station_id"]) for r in missing_station_rows}
        if returned_keys != expected_keys:
            raise RuntimeError("station catalog INSERT RETURNING mismatch")
        counts["stations_inserted"] = len(returned)

    _notify(progress, "profiles")
    profile_plan = _unique(plan["profiles"], _identity, "profile identity")
    profile_keys = list(profile_plan)
    existing_profile_rows = []
    if profile_keys:
        existing_profile_rows = _mapping_rows(session.execute(select(
            AirPollutionBaselineProfile.id,
            *(getattr(AirPollutionBaselineProfile, field) for field in IDENTITY_FIELDS),
        ).where(tuple_(
            *(getattr(AirPollutionBaselineProfile, field) for field in IDENTITY_FIELDS)
        ).in_(profile_keys))))
    profiles = {_identity(row): row["id"] for row in existing_profile_rows}
    missing_profiles = [row for key, row in profile_plan.items() if key not in profiles]
    if missing_profiles:
        returned = _mapping_rows(session.execute(
            insert(AirPollutionBaselineProfile).returning(
                AirPollutionBaselineProfile.id,
                *(getattr(AirPollutionBaselineProfile, field) for field in IDENTITY_FIELDS),
            ), missing_profiles,
        ))
        for row in returned:
            profiles[_identity(row)] = row["id"]
        if len(returned) != len(missing_profiles) or any(key not in profiles for key in profile_plan):
            raise RuntimeError("profile INSERT RETURNING mismatch")
        counts["profiles_inserted"] = len(returned)

    _notify(progress, "versions")
    version_plan = {}
    hashes_by_profile: dict[int, set[str]] = {}
    for row in plan["versions"]:
        profile_key = _identity(row["profile_identity"])
        profile_id = profiles.get(profile_key)
        if profile_id is None:
            raise ValueError(f"version references missing profile: {profile_key}")
        key = (profile_id, row["content_sha256"])
        if key in version_plan:
            raise ValueError(f"duplicate baseline version in import plan: {key}")
        version_plan[key] = row
        hashes_by_profile.setdefault(profile_id, set()).add(row["content_sha256"])
        if row.get("parent_content_sha256"):
            hashes_by_profile[profile_id].add(row["parent_content_sha256"])

    profile_ids = list(hashes_by_profile)
    all_hashes = sorted({digest for values in hashes_by_profile.values() for digest in values})
    existing_version_rows = []
    if profile_ids and all_hashes:
        existing_version_rows = _mapping_rows(session.execute(select(
            AirPollutionBaselineVersion.id,
            AirPollutionBaselineVersion.profile_id,
            AirPollutionBaselineVersion.content_sha256,
        ).where(
            AirPollutionBaselineVersion.profile_id.in_(profile_ids),
            AirPollutionBaselineVersion.content_sha256.in_(all_hashes),
        )))
    versions = {
        (row["profile_id"], row["content_sha256"]): row["id"]
        for row in existing_version_rows
        if row["content_sha256"] in hashes_by_profile.get(row["profile_id"], set())
    }

    expected_bucket_counts = Counter(
        (profiles[_identity(row["profile_identity"])], row["content_sha256"])
        for row in plan["buckets"]
    )
    existing_targets = {key: versions[key] for key in version_plan if key in versions}
    if existing_targets:
        count_rows = _mapping_rows(session.execute(select(
            AirPollutionBaselineBucket.baseline_version_id,
            func.count().label("bucket_count"),
        ).where(
            AirPollutionBaselineBucket.baseline_version_id.in_(list(existing_targets.values()))
        ).group_by(AirPollutionBaselineBucket.baseline_version_id)))
        actual_counts = {row["baseline_version_id"]: row["bucket_count"] for row in count_rows}
        for key, version_id in existing_targets.items():
            if actual_counts.get(version_id, 0) != expected_bucket_counts[key]:
                raise ValueError(f"existing baseline version is incomplete: {key[1]}")
        counts["versions_existing"] = len(existing_targets)

    pending = {key: row for key, row in version_plan.items() if key not in versions}
    new_version_keys = set(pending)
    while pending:
        ready = []
        for key, row in pending.items():
            parent_hash = row.get("parent_content_sha256")
            parent_key = (key[0], parent_hash) if parent_hash else None
            if parent_key is None or parent_key in versions:
                values = {k: v for k, v in row.items()
                          if k not in {"profile_identity", "parent_content_sha256", "lifecycle_status"}}
                ready.append({
                    **values,
                    "profile_id": key[0],
                    "parent_version_id": versions.get(parent_key),
                    "imported_at": imported_at,
                    "lifecycle_status": "draft",
                })
        if not ready:
            unresolved = sorted((profile_id, row.get("parent_content_sha256"))
                                for (profile_id, _), row in pending.items())
            raise ValueError(f"missing or cyclic parent baseline version: {unresolved}")
        returned = _mapping_rows(session.execute(
            insert(AirPollutionBaselineVersion).returning(
                AirPollutionBaselineVersion.id,
                AirPollutionBaselineVersion.profile_id,
                AirPollutionBaselineVersion.content_sha256,
            ), ready,
        ))
        returned_keys = {(r["profile_id"], r["content_sha256"]) for r in returned}
        ready_keys = {(r["profile_id"], r["content_sha256"]) for r in ready}
        if returned_keys != ready_keys:
            raise RuntimeError("version INSERT RETURNING mismatch")
        for row in returned:
            key = (row["profile_id"], row["content_sha256"])
            versions[key] = row["id"]
            pending.pop(key)
        counts["versions_inserted"] += len(returned)

    bucket_values = []
    for row in plan["buckets"]:
        profile_id = profiles[_identity(row["profile_identity"])]
        version_key = (profile_id, row["content_sha256"])
        if version_key not in new_version_keys:
            continue
        values = {k: v for k, v in row.items()
                  if k not in {"profile_identity", "content_sha256"}}
        bucket_values.append({**values, "baseline_version_id": versions[version_key]})
    counts["buckets_inserted"] = len(bucket_values)
    total = len(bucket_values)
    _notify(progress, f"buckets 0 / {total}")
    next_report = 10_000
    for start in range(0, total, BUCKET_CHUNK_SIZE):
        chunk = bucket_values[start:start + BUCKET_CHUNK_SIZE]
        session.execute(insert(AirPollutionBaselineBucket), chunk)
        completed = start + len(chunk)
        if completed >= next_report or completed == total:
            _notify(progress, f"buckets {completed} / {total}")
            next_report = ((completed // 10_000) + 1) * 10_000
    return counts


def import_baseline_plan(
    plan: dict[str, Any], *, progress: Progress | None = None
) -> dict[str, int]:
    """Explicit write entry point; any exception rolls the single transaction back."""
    imported_at = datetime.now(timezone.utc)
    with Session.begin() as session:
        result = persist_import_plan(
            session, plan, imported_at=imported_at, progress=progress,
        )
    _notify(progress, "commit complete")
    return result
