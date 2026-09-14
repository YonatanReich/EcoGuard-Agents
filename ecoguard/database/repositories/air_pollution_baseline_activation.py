"""Guarded, atomic lifecycle promotion for Air Pollution baseline cohorts."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select, text, update

from ecoguard.database.engine import Session
from ecoguard.database.models import (
    AirPollutionBaselineBucket,
    AirPollutionBaselineProfile,
    AirPollutionBaselineVersion,
)
from services.air_pollution_baseline_activation import (
    EXPECTED_TARGET_PROFILES,
    BaselineActivationError,
    assess_activation_cohort,
    require_target_family,
)


def _mappings(result) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().all()]


def read_activation_snapshot(session, *, family: str, lock: bool) -> dict[str, Any]:
    """Read the complete target cohort, optionally locking mutable rows."""
    require_target_family(family)
    profile_statement = select(
        AirPollutionBaselineProfile.id,
        AirPollutionBaselineProfile.baseline_family,
    ).where(
        AirPollutionBaselineProfile.baseline_family == family
    ).order_by(AirPollutionBaselineProfile.id)
    if lock:
        profile_statement = profile_statement.with_for_update()
    profiles = _mappings(session.execute(profile_statement))
    profile_ids = [row["id"] for row in profiles]

    versions: list[dict[str, Any]] = []
    bucket_counts: dict[int, int] = {}
    if profile_ids:
        version_statement = select(
            AirPollutionBaselineVersion.id,
            AirPollutionBaselineVersion.profile_id,
            AirPollutionBaselineVersion.lifecycle_status,
            AirPollutionBaselineVersion.coverage_status,
            AirPollutionBaselineProfile.baseline_family.label("baseline_family"),
        ).join(
            AirPollutionBaselineProfile,
            AirPollutionBaselineProfile.id == AirPollutionBaselineVersion.profile_id,
        ).where(
            AirPollutionBaselineVersion.profile_id.in_(profile_ids)
        ).order_by(
            AirPollutionBaselineVersion.profile_id,
            AirPollutionBaselineVersion.id,
        )
        if lock:
            version_statement = version_statement.with_for_update(
                of=AirPollutionBaselineVersion
            )
        versions = _mappings(session.execute(version_statement))
        draft_ids = [
            row["id"] for row in versions if row["lifecycle_status"] == "draft"
        ]
        if draft_ids:
            counts = _mappings(session.execute(select(
                AirPollutionBaselineBucket.baseline_version_id,
                func.count(AirPollutionBaselineBucket.id).label("bucket_count"),
            ).where(
                AirPollutionBaselineBucket.baseline_version_id.in_(draft_ids)
            ).group_by(AirPollutionBaselineBucket.baseline_version_id)))
            bucket_counts = {
                int(row["baseline_version_id"]): int(row["bucket_count"])
                for row in counts
            }
    return {
        "profiles": profiles,
        "versions": versions,
        "bucket_counts": bucket_counts,
    }


def _assess(session, *, family: str, lock: bool, expected_profile_count: int):
    snapshot = read_activation_snapshot(session, family=family, lock=lock)
    return assess_activation_cohort(
        family=family,
        expected_profile_count=expected_profile_count,
        **snapshot,
    )


def audit_baseline_family_activation(
    *, family: str, expected_profile_count: int = EXPECTED_TARGET_PROFILES,
) -> dict[str, Any]:
    """Run the default readiness mode in an explicitly read-only transaction."""
    require_target_family(family)
    with Session() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        report = _assess(
            session, family=family, lock=False,
            expected_profile_count=expected_profile_count,
        )
        session.rollback()
    return report


def activate_baseline_family_in_session(
    session, *, family: str,
    expected_profile_count: int = EXPECTED_TARGET_PROFILES,
) -> dict[str, Any]:
    """Revalidate locked rows, then supersede and activate in update order."""
    before = _assess(
        session, family=family, lock=True,
        expected_profile_count=expected_profile_count,
    )
    if not before["ready"]:
        raise BaselineActivationError("; ".join(before["errors"]))

    old_active_ids = before["existing_active_version_ids"]
    target_ids = before["target_draft_version_ids"]
    if old_active_ids:
        result = session.execute(update(AirPollutionBaselineVersion).where(
            AirPollutionBaselineVersion.id.in_(old_active_ids),
            AirPollutionBaselineVersion.lifecycle_status == "active",
        ).values(lifecycle_status="superseded"))
        if result.rowcount != len(old_active_ids):
            raise BaselineActivationError("existing_active_supersede_count_mismatch")

    result = session.execute(update(AirPollutionBaselineVersion).where(
        AirPollutionBaselineVersion.id.in_(target_ids),
        AirPollutionBaselineVersion.lifecycle_status == "draft",
    ).values(lifecycle_status="active"))
    if result.rowcount != len(target_ids):
        raise BaselineActivationError("draft_activation_count_mismatch")

    final_rows = _mappings(session.execute(select(
        AirPollutionBaselineVersion.id,
        AirPollutionBaselineVersion.profile_id,
        AirPollutionBaselineVersion.lifecycle_status,
    ).where(
        AirPollutionBaselineVersion.profile_id.in_(before["target_profile_ids"])
    )))
    final_by_id = {int(row["id"]): row for row in final_rows}
    if any(final_by_id.get(version_id, {}).get("lifecycle_status") != "active"
           for version_id in target_ids):
        raise BaselineActivationError("post_activation_target_verification_failed")
    if any(final_by_id.get(version_id, {}).get("lifecycle_status") != "superseded"
           for version_id in old_active_ids):
        raise BaselineActivationError("post_activation_supersede_verification_failed")
    active_per_profile: dict[int, int] = {}
    for row in final_rows:
        if row["lifecycle_status"] == "active":
            profile_id = int(row["profile_id"])
            active_per_profile[profile_id] = active_per_profile.get(profile_id, 0) + 1
    if set(active_per_profile) != set(before["target_profile_ids"]) or any(
        count != 1 for count in active_per_profile.values()
    ):
        raise BaselineActivationError("post_activation_unique_active_verification_failed")
    final_lifecycle = Counter(row["lifecycle_status"] for row in final_rows)

    return {
        "family": family,
        "before": before["counts"],
        "after": {
            "profiles": len(before["target_profile_ids"]),
            "versions": len(final_rows),
            "lifecycle": dict(sorted(final_lifecycle.items())),
            "active": len(target_ids),
            "draft": 0,
            "superseded_in_transaction": len(old_active_ids),
        },
        "activated_version_ids": target_ids,
        "superseded_version_ids": old_active_ids,
        "activated_count": len(target_ids),
        "superseded_count": len(old_active_ids),
        "final_active_count": final_lifecycle.get("active", 0),
    }


def activate_baseline_family(
    *, family: str, expected_profile_count: int = EXPECTED_TARGET_PROFILES,
) -> dict[str, Any]:
    """Atomic write entry point; transaction context rolls back every failure."""
    require_target_family(family)
    with Session.begin() as session:
        # Predicate reads plus row locks protect this one-off cohort operation
        # from concurrent imports introducing a phantom target.
        session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
        result = activate_baseline_family_in_session(
            session,
            family=family,
            expected_profile_count=expected_profile_count,
        )
    return result
