"""Pure readiness policy for atomic Air Pollution baseline activation."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

TARGET_BASELINE_FAMILY = "five_minute_observation"
EXPECTED_TARGET_PROFILES = 388
EXPECTED_BUCKETS_PER_VERSION = 288
ALLOWED_COVERAGE_STATUSES = frozenset({"FULL_BASELINE", "PARTIAL_BASELINE"})
ALLOWED_LIFECYCLE_STATUSES = frozenset({"draft", "active", "superseded"})


class BaselineActivationError(RuntimeError):
    """The cohort failed validation or could not be changed atomically."""


def require_target_family(family: str) -> None:
    if family != TARGET_BASELINE_FAMILY:
        raise ValueError(
            f"activation family must be exactly {TARGET_BASELINE_FAMILY!r}"
        )


def assess_activation_cohort(
    *,
    family: str,
    profiles: Sequence[Mapping[str, Any]],
    versions: Sequence[Mapping[str, Any]],
    bucket_counts: Mapping[int, int],
    expected_profile_count: int = EXPECTED_TARGET_PROFILES,
) -> dict[str, Any]:
    """Validate a locked/read-only snapshot without changing lifecycle state."""
    require_target_family(family)
    errors: list[str] = []
    profile_ids = [int(row["id"]) for row in profiles]
    profile_id_set = set(profile_ids)
    if len(profile_ids) != len(profile_id_set):
        errors.append("duplicate_profile_rows")
    if len(profile_ids) != expected_profile_count:
        errors.append(
            f"profile_count_mismatch:expected={expected_profile_count}:actual={len(profile_ids)}"
        )
    if any(row.get("baseline_family") != family for row in profiles):
        errors.append("unexpected_profile_family")

    versions_by_profile: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for version in versions:
        profile_id = int(version["profile_id"])
        if profile_id not in profile_id_set:
            errors.append(f"orphaned_target_version:{version['id']}")
            continue
        if version.get("baseline_family") != family:
            errors.append(f"profile_version_family_mismatch:{version['id']}")
        if version.get("lifecycle_status") not in ALLOWED_LIFECYCLE_STATUSES:
            errors.append(f"unexpected_lifecycle_status:{version['id']}")
        versions_by_profile[profile_id].append(version)

    target_drafts: list[Mapping[str, Any]] = []
    existing_active: list[Mapping[str, Any]] = []
    for profile_id in profile_ids:
        profile_versions = versions_by_profile.get(profile_id, [])
        drafts = [row for row in profile_versions if row.get("lifecycle_status") == "draft"]
        active = [row for row in profile_versions if row.get("lifecycle_status") == "active"]
        if len(drafts) != 1:
            errors.append(f"profile_draft_count:{profile_id}:{len(drafts)}")
        else:
            target_drafts.append(drafts[0])
        if len(active) > 1:
            errors.append(f"profile_active_count:{profile_id}:{len(active)}")
        existing_active.extend(active)

    coverage_counts = Counter()
    total_target_buckets = 0
    for draft in target_drafts:
        version_id = int(draft["id"])
        coverage = str(draft.get("coverage_status"))
        coverage_counts[coverage] += 1
        if coverage not in ALLOWED_COVERAGE_STATUSES:
            errors.append(f"unexpected_coverage_status:{version_id}:{coverage}")
        bucket_count = int(bucket_counts.get(version_id, 0))
        total_target_buckets += bucket_count
        if bucket_count != EXPECTED_BUCKETS_PER_VERSION:
            errors.append(
                f"incomplete_draft_version:{version_id}:buckets={bucket_count}"
            )

    lifecycle_counts = Counter(str(row.get("lifecycle_status")) for row in versions)
    target_ids = [int(row["id"]) for row in target_drafts]
    active_ids = [int(row["id"]) for row in existing_active]
    return {
        "family": family,
        "ready": not errors,
        "errors": errors,
        "counts": {
            "profiles": len(profile_ids),
            "versions": len(versions),
            "lifecycle": dict(sorted(lifecycle_counts.items())),
            "target_drafts": len(target_ids),
            "existing_active": len(active_ids),
            "coverage": dict(sorted(coverage_counts.items())),
            "target_buckets": total_target_buckets,
        },
        "target_profile_ids": profile_ids,
        "target_draft_version_ids": target_ids,
        "existing_active_version_ids": active_ids,
        "projected_after": {
            "active": len(target_ids),
            "draft": 0,
            "newly_superseded": len(active_ids),
        },
    }
