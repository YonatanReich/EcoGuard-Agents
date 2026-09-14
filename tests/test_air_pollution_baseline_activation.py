"""Focused activation policy tests; no database connection."""

import json

import pytest

from services.air_pollution_baseline_activation import (
    TARGET_BASELINE_FAMILY,
    assess_activation_cohort,
)


def profile(profile_id):
    return {"id": profile_id, "baseline_family": TARGET_BASELINE_FAMILY}


def version(version_id, profile_id, lifecycle="draft", coverage="FULL_BASELINE"):
    return {
        "id": version_id,
        "profile_id": profile_id,
        "baseline_family": TARGET_BASELINE_FAMILY,
        "lifecycle_status": lifecycle,
        "coverage_status": coverage,
    }


def assess(profiles, versions, counts, expected=2):
    return assess_activation_cohort(
        family=TARGET_BASELINE_FAMILY,
        profiles=profiles,
        versions=versions,
        bucket_counts=counts,
        expected_profile_count=expected,
    )


def test_complete_cohort_is_ready_and_projects_one_active_per_profile():
    result = assess(
        [profile(1), profile(2)],
        [version(11, 1), version(22, 2, coverage="PARTIAL_BASELINE")],
        {11: 288, 22: 288},
    )

    assert result["ready"] is True
    assert result["target_draft_version_ids"] == [11, 22]
    assert result["counts"]["coverage"] == {
        "FULL_BASELINE": 1, "PARTIAL_BASELINE": 1,
    }
    assert result["projected_after"]["active"] == 2


@pytest.mark.parametrize("versions,counts,error", [
    ([version(11, 1)], {11: 288}, "profile_draft_count:2:0"),
    ([version(11, 1), version(12, 1), version(22, 2)],
     {11: 288, 12: 288, 22: 288}, "profile_draft_count:1:2"),
    ([version(11, 1), version(22, 2)], {11: 287, 22: 288},
     "incomplete_draft_version:11:buckets=287"),
    ([version(11, 1, coverage="INSUFFICIENT_HISTORY"), version(22, 2)],
     {11: 288, 22: 288}, "unexpected_coverage_status:11:INSUFFICIENT_HISTORY"),
])
def test_invalid_cohorts_fail_closed(versions, counts, error):
    result = assess([profile(1), profile(2)], versions, counts)
    assert result["ready"] is False
    assert error in result["errors"]


def test_wrong_family_is_rejected_before_assessment():
    with pytest.raises(ValueError, match="five_minute_observation"):
        assess_activation_cohort(
            family="completed_hour", profiles=[], versions=[], bucket_counts={},
        )


def test_multiple_active_versions_violate_unique_active_invariant():
    result = assess(
        [profile(1), profile(2)],
        [
            version(11, 1), version(10, 1, lifecycle="active"),
            version(9, 1, lifecycle="active"), version(22, 2),
        ],
        {11: 288, 22: 288},
    )

    assert result["ready"] is False
    assert "profile_active_count:1:2" in result["errors"]


def test_cli_dry_run_never_calls_activation(monkeypatch, capsys):
    import scripts.activate_air_pollution_baselines as cli

    readiness = assess([profile(1), profile(2)],
                       [version(11, 1), version(22, 2)],
                       {11: 288, 22: 288})
    monkeypatch.setattr(cli, "audit", lambda family: readiness)
    monkeypatch.setattr(
        cli, "activate",
        lambda family: pytest.fail("dry-run attempted a lifecycle write"),
    )

    assert cli.main(["--family", TARGET_BASELINE_FAMILY]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "DRY_RUN"
    assert output["database_modified"] is False


def test_cli_write_requires_both_guards():
    import scripts.activate_air_pollution_baselines as cli

    with pytest.raises(SystemExit):
        cli.main(["--family", TARGET_BASELINE_FAMILY, "--write"])


def test_real_cli_write_wrapper_returns_repository_result(monkeypatch, capsys):
    """Regression: exercise CLI -> wrapper -> repository, not a patched wrapper."""
    import scripts.activate_air_pollution_baselines as cli
    from ecoguard.database.repositories import air_pollution_baseline_activation as repository

    readiness = assess(
        [profile(1), profile(2)], [version(11, 1), version(22, 2)],
        {11: 288, 22: 288},
    )
    repository_result = {
        "family": TARGET_BASELINE_FAMILY,
        "before": readiness["counts"],
        "after": {
            "profiles": 2, "versions": 2, "lifecycle": {"active": 2},
            "active": 2, "draft": 0, "superseded_in_transaction": 0,
        },
        "activated_version_ids": [11, 22],
        "superseded_version_ids": [],
        "activated_count": 2,
        "superseded_count": 0,
        "final_active_count": 2,
    }
    calls = []
    monkeypatch.setattr(cli, "audit", lambda family: readiness)
    monkeypatch.setattr(
        repository,
        "activate_baseline_family",
        lambda **kwargs: calls.append(kwargs) or repository_result,
    )

    assert cli.main([
        "--family", TARGET_BASELINE_FAMILY, "--write", "--confirm-write",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert calls == [{
        "family": TARGET_BASELINE_FAMILY,
        "expected_profile_count": 388,
    }]
    assert output["database_modified"] is True
    assert output["activation"]["family"] == TARGET_BASELINE_FAMILY
    assert output["activation"]["before"] == readiness["counts"]
    assert output["activation"]["activated_count"] == 2
    assert output["activation"]["superseded_count"] == 0
    assert output["activation"]["final_active_count"] == 2
